"""Build the local RAG index from stories, knowledge base markdown and Figma UX intent."""
import json
import re
from pathlib import Path
from typing import Any

from rag.embeddings import get_embedder
from rag.freshness import build_manifest, hash_file, hash_text, ux_hash
from rag.store import Chunk, VectorStore


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _chunk(
    *,
    id: str,
    text: str,
    source: str,
    doc_type: str,
    source_path: str,
    source_version: str,
    meta: dict[str, Any] | None = None,
) -> Chunk:
    metadata = {
        "doc_type": doc_type,
        "source_path": source_path,
        "source_version": source_version,
        "content_hash": hash_text(text),
        **(meta or {}),
    }
    return Chunk(id=id, text=text, source=source, meta=metadata)


def _markdown_doc_type(path: Path, rule_id: str | None) -> str:
    if rule_id:
        return "business_rule"
    return {
        "api_contract": "api_contract",
        "test_data": "test_data",
        "glossary": "glossary",
        "business_rules": "business_rule_group",
    }.get(path.stem, "knowledge")


def chunk_markdown(path: Path) -> list[Chunk]:
    """One chunk per heading section; keeps the document title as context."""
    text = path.read_text(encoding="utf-8")
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
    source_path = f"knowledge_base/{path.name}"
    source_version = hash_file(path)
    chunks, heading, parent_heading, buf = [], title, "", []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            rule_match = re.search(r"\b(BR-[A-Z0-9]+-\d+)\b", heading, re.IGNORECASE)
            rule_id = rule_match.group(1).upper() if rule_match else None
            metadata: dict[str, Any] = {"heading": heading}
            if parent_heading:
                metadata["section"] = parent_heading
                metadata["feature"] = _slug(parent_heading)
            if rule_id:
                metadata["rule_id"] = rule_id
            chunks.append(_chunk(
                id=f"{path.stem}#{_slug(heading)}",
                text=f"{title} > {heading}\n{body}",
                source=f"{source_path}#{_slug(heading)}",
                doc_type=_markdown_doc_type(path, rule_id),
                source_path=source_path,
                source_version=source_version,
                meta=metadata,
            ))

    for line in text.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            flush()
            if len(m.group(1)) == 2:
                parent_heading = m.group(2).strip()
            heading, buf = m.group(2).strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    flush()
    return chunks


def chunk_stories(stories_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(stories_dir.glob("*.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        source_path = f"stories/{path.name}"
        source_version = hash_file(path)
        common = {
            "story": s["key"],
            "labels": s.get("labels", []),
            "feature": s.get("labels", []),
            "frames": s.get("figma_frames", []),
            "rule_ids": s.get("business_rules", []),
        }
        chunks.append(_chunk(
            id=s["key"],
            text=f"{s['key']} {s['title']}\n{s['description']}\nRules: {', '.join(s.get('business_rules', []))}",
            source=source_path,
            doc_type="story",
            source_path=source_path,
            source_version=source_version,
            meta=common,
        ))
        for ac in s["acceptance_criteria"]:
            mentioned_rules = sorted(set(re.findall(r"\bBR-[A-Z0-9]+-\d+\b", ac["text"], re.IGNORECASE)))
            chunks.append(_chunk(
                id=f"{s['key']}:{ac['id']}",
                text=f"{s['key']} {ac['id']}: {ac['text']}",
                source=f"{source_path}#{ac['id']}",
                doc_type="ac",
                source_path=source_path,
                source_version=source_version,
                meta={**common, "ac": ac["id"], "rule_ids": mentioned_rules},
            ))
    return chunks


def chunk_ux(ux: dict) -> list[Chunk]:
    chunks = []
    version = str(ux.get("version") or ux_hash(ux) or "unknown")
    features = ux.get("features", [])

    def frame_features(frame: str) -> list[str]:
        return sorted({
            str(feature.get("id") or feature.get("name"))
            for feature in features
            if frame in feature.get("frames", []) and (feature.get("id") or feature.get("name"))
        })

    for frame, components in ux.get("frames", {}).items():
        lines = [f"- {c['kind']} '{c['label']}'" + (f" columns={c.get('columns')}" if c.get("columns") else "")
                 + (f" -> {c['navigates_to']}" if c.get("navigates_to") else "") for c in components]
        chunks.append(_chunk(
            id=f"figma:{frame}",
            text=f"Figma frame '{frame}' components:\n" + "\n".join(lines),
            source=f"figma/{_slug(frame)}",
            doc_type="figma_frame",
            source_path="figma",
            source_version=version,
            meta={
                "frame": frame,
                "feature": frame_features(frame),
                "node_ids": [c.get("node_id") for c in components if c.get("node_id")],
                "component_kinds": [c.get("kind") for c in components if c.get("kind")],
            },
        ))
    for v in ux.get("approved_variances", []):
        frame = v.get("frame")
        chunks.append(_chunk(
            id=f"figma-variance:{v.get('node_id')}",
            text=f"Approved variance on '{v.get('frame')}' for '{v.get('label')}': {json.dumps(v)}",
            source="figma/approved-variances",
            doc_type="figma_variance",
            source_path="figma",
            source_version=version,
            meta={
                "frame": frame,
                "feature": frame_features(frame) if frame else [],
                "node_id": v.get("node_id"),
            },
        ))
    return chunks


def chunk_flow_test_data(path: Path) -> list[Chunk]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    source_path = f"knowledge_base/{path.name}"
    source_version = hash_file(path)
    chunks = []
    for trigger, inputs in sorted(data.get("prerequisites", {}).items()):
        frame, _, label = trigger.partition("/")
        text = (
            f"Figma flow prerequisite for {trigger}:\n"
            + "\n".join(f"- {item.get('label')}: {item.get('value')}" for item in inputs)
        )
        chunks.append(_chunk(
            id=f"flow_test_data#{_slug(trigger)}",
            text=text,
            source=f"{source_path}#{_slug(trigger)}",
            doc_type="flow_test",
            source_path=source_path,
            source_version=source_version,
            meta={"frame": frame, "trigger": label, "feature": _slug(frame)},
        ))
    return chunks


def build_index(stories_dir: Path, knowledge_dir: Path, index_dir: Path, ux: dict | None,
                embedding_provider: str, embedding_model: str) -> VectorStore:
    chunks = chunk_stories(stories_dir)
    for md in sorted(knowledge_dir.glob("*.md")):
        chunks.extend(chunk_markdown(md))
    chunks.extend(chunk_flow_test_data(knowledge_dir / "flow_test_data.json"))
    if ux:
        chunks.extend(chunk_ux(ux))
    embedder = get_embedder(embedding_provider, embedding_model)
    vectors = embedder.embed([c.text for c in chunks])
    store = VectorStore(index_dir)
    store.build(chunks, vectors, embedder.name)
    manifest = build_manifest(
        stories_dir,
        knowledge_dir,
        chunks=chunks,
        embedder_name=embedder.name,
        ux=ux,
    )
    store.save(manifest)
    return store
