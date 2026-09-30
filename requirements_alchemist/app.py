"""Local-first web application for generation, review, chat, and publication."""
from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session

from requirements_alchemist.config import Settings
from requirements_alchemist.generation import RequirementsLLM
from requirements_alchemist.models import GenerationInput, SourceDocument, SourceKind
from requirements_alchemist.outputs import (
    JiraPublisher,
    export_assurance_bundle,
    export_excel,
    import_excel_review,
    load_package,
    save_package,
)
from requirements_alchemist.retrieval import ReferenceCorpus
from requirements_alchemist.sources import SourceLoader, text_document


class Workspace:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.loader = SourceLoader(settings)
        self.llm = RequirementsLLM(settings)
        self.corpus = ReferenceCorpus(settings.reference_dir)
        self.documents: list[SourceDocument] = []
        self.package = None
        self.chat_history: list[dict] = []
        self.lock = threading.RLock()
        self.rebuild()

    def rebuild(self) -> None:
        documents = list(self.documents)
        if self.package:
            for story in self.package.stories:
                documents.append(
                    SourceDocument(
                        id=f"generated-{story.local_id.lower()}",
                        kind=SourceKind.JIRA,
                        title=story.title,
                        text=json.dumps(story.model_dump(), indent=2),
                        metadata={"generated": True, "package_id": self.package.id},
                    )
                )
        self.corpus.rebuild(documents)

    def canonical_path(self) -> Path:
        if not self.package:
            raise ValueError("No generated package is available")
        return self.settings.output_dir / f"{self.package.id}.json"

    def persist(self) -> None:
        save_package(self.package, self.canonical_path())
        self.rebuild()


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.load()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = secrets.token_hex(32)
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024)
    workspace = Workspace(settings)
    app.extensions["requirements_alchemist"] = workspace

    @app.before_request
    def verify_csrf():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not secrets.compare_digest(supplied, session.get("csrf", "")):
                return jsonify({"error": "invalid CSRF token"}), 403

    @app.errorhandler(Exception)
    def error(exc):
        status = getattr(exc, "code", 500)
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), status

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_urlsafe(24))
        return render_template(
            "index.html",
            csrf=session["csrf"],
            app_name=settings.name,
            jira_enabled=settings.jira_push_enabled,
            provider=settings.llm_provider,
            model=settings.llm_model,
        )

    @app.get("/api/state")
    def state():
        return jsonify(
            {
                "sources": [doc.model_dump(mode="json") for doc in workspace.documents],
                "package": workspace.package.model_dump(mode="json") if workspace.package else None,
                "jira_enabled": settings.jira_push_enabled,
            }
        )

    @app.post("/api/sources/text")
    def add_text_source():
        payload = request.get_json(force=True)
        text = str(payload.get("text", ""))[: settings.source_max_chars]
        if not text.strip():
            raise ValueError("Source text is required")
        document = text_document(payload.get("title", "Pasted PRD"), text)
        with workspace.lock:
            workspace.documents = [d for d in workspace.documents if d.id != document.id]
            workspace.documents.append(document)
            workspace.rebuild()
        return jsonify(document.model_dump(mode="json")), 201

    @app.post("/api/sources/upload")
    def upload_source():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            raise ValueError("A file is required")
        suffix = Path(uploaded.filename).suffix.lower()
        if suffix not in {".txt", ".md", ".json", ".yaml", ".yml"}:
            raise ValueError("Supported uploads: .txt, .md, .json, .yaml, .yml")
        raw = uploaded.read(settings.source_max_chars + 1)
        if len(raw) > settings.source_max_chars:
            raise ValueError("Source file exceeds the configured size limit")
        document = text_document(uploaded.filename, raw.decode("utf-8"))
        with workspace.lock:
            workspace.documents.append(document)
            workspace.rebuild()
        return jsonify(document.model_dump(mode="json")), 201

    @app.post("/api/sources/url")
    def add_url_source():
        payload = request.get_json(force=True)
        document = workspace.loader.load_url(str(payload.get("url", "")))
        with workspace.lock:
            workspace.documents = [d for d in workspace.documents if d.id != document.id]
            workspace.documents.append(document)
            workspace.rebuild()
        return jsonify(document.model_dump(mode="json")), 201

    @app.delete("/api/sources/<source_id>")
    def delete_source(source_id: str):
        with workspace.lock:
            before = len(workspace.documents)
            workspace.documents = [d for d in workspace.documents if d.id != source_id]
            workspace.rebuild()
        return jsonify({"deleted": before - len(workspace.documents)})

    @app.post("/api/generate")
    def generate():
        generation = GenerationInput.model_validate(request.get_json(force=True))
        with workspace.lock:
            if generation.prd_text.strip():
                workspace.documents.append(
                    text_document(generation.title, generation.prd_text[: settings.source_max_chars])
                )
            for url in generation.source_urls + generation.figma_urls:
                workspace.documents.append(workspace.loader.load_url(url))
            if not workspace.documents:
                raise ValueError("Add PRD, Figma, Confluence, or Jira evidence first")
            query = generation.reference_query or (
                f"{generation.title} {generation.objective} "
                + " ".join(document.title for document in workspace.documents)
            )
            references = [
                item
                for item in workspace.corpus.search(query, k=settings.retrieval_top_k)
                if item.metadata.get("license") or item.source_id.startswith("reference-")
            ]
            workspace.package = workspace.llm.generate(
                generation, workspace.documents, references
            )
            workspace.persist()
        return jsonify(workspace.package.model_dump(mode="json")), 201

    @app.patch("/api/stories/<local_id>/review")
    def review_story(local_id: str):
        payload = request.get_json(force=True)
        with workspace.lock:
            if not workspace.package:
                raise ValueError("No generated package is available")
            story = next(
                (item for item in workspace.package.stories if item.local_id == local_id),
                None,
            )
            if not story:
                raise ValueError(f"Unknown story: {local_id}")
            status = str(payload.get("status", story.review_status)).upper()
            if status not in {"DRAFT", "APPROVED", "REJECTED", "NEEDS_CHANGE"}:
                raise ValueError("Invalid review status")
            story.review_status = status
            story.reviewer = str(payload.get("reviewer", story.reviewer))
            story.review_comment = str(payload.get("comment", story.review_comment))
            workspace.persist()
        return jsonify(story.model_dump(mode="json"))

    @app.post("/api/stories/<local_id>/reference")
    def add_reference(local_id: str):
        payload = request.get_json(silent=True) or {}
        with workspace.lock:
            if not workspace.package:
                raise ValueError("No generated package is available")
            story = next(
                (item for item in workspace.package.stories if item.local_id == local_id),
                None,
            )
            if not story:
                raise ValueError(f"Unknown story: {local_id}")
            path = workspace.corpus.add_exemplary_story(
                story,
                reviewer=str(payload.get("reviewer") or story.reviewer),
            )
            workspace.rebuild()
        return jsonify({"saved": str(path.relative_to(settings.reference_dir))}), 201

    @app.get("/api/export/excel")
    def download_excel():
        if not workspace.package:
            raise ValueError("No generated package is available")
        path = settings.output_dir / f"{workspace.package.id}-review.xlsx"
        export_excel(workspace.package, path, settings.secret_values())
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.get("/api/export/assurance")
    def download_assurance():
        if not workspace.package:
            raise ValueError("No generated package is available")
        path = settings.output_dir / f"{workspace.package.id}-assurance-stories.zip"
        export_assurance_bundle(workspace.package, path)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.post("/api/review/import")
    def import_review():
        uploaded = request.files.get("file")
        if not uploaded or not workspace.package:
            raise ValueError("Review workbook and generated package are required")
        temporary = settings.workspace_dir / "imports" / Path(uploaded.filename or "review.xlsx").name
        temporary.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(temporary)
        with workspace.lock:
            workspace.package = import_excel_review(
                temporary, workspace.package, settings.secret_values()
            )
            workspace.persist()
        temporary.unlink(missing_ok=True)
        return jsonify(workspace.package.model_dump(mode="json"))

    @app.post("/api/publish/jira")
    def publish_jira():
        with workspace.lock:
            if not workspace.package:
                raise ValueError("No generated package is available")
            results = JiraPublisher(settings).publish(workspace.package)
            workspace.persist()
        return jsonify([result.model_dump(mode="json") for result in results])

    @app.post("/api/chat")
    def chat():
        payload = request.get_json(force=True)
        question = str(payload.get("message", "")).strip()
        if not question:
            raise ValueError("Chat message is required")
        context = workspace.corpus.search(question, k=settings.retrieval_top_k)
        answer = workspace.llm.chat(question, context, workspace.chat_history)
        workspace.chat_history.extend(
            [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        )
        workspace.chat_history = workspace.chat_history[-16:]
        return jsonify(
            {
                "answer": answer,
                "sources": [
                    {"id": item.source_id, "title": item.title, "score": item.score}
                    for item in context
                ],
            }
        )

    @app.post("/api/workspace/reset")
    def reset():
        with workspace.lock:
            workspace.documents = []
            workspace.package = None
            workspace.chat_history = []
            workspace.rebuild()
        return jsonify({"reset": True})

    return app
