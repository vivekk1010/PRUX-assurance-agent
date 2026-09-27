"""Build the local RAG index from stories, knowledge base markdown and Figma UX intent."""
import json
import re
from pathlib import Path

from rag.embeddings import get_embedder
from rag.store import Chunk, VectorStore


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def chunk_markdown(path: Path) -> list[Chunk]:
    """One chunk per heading section; keeps the document title as context."""
    text = path.read_text(encoding="utf-8")
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
    chunks, heading, buf = [], title, []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(
                id=f"{path.stem}#{_slug(heading)}",
                text=f"{title} > {heading}\n{body}",
                source=f"knowledge_base/{path.name}#{_slug(heading)}",
                meta={"heading": heading},
            ))

    for line in text.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            flush()
            heading, buf = m.group(2).strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    flush()
    return chunks


def chunk_stories(stories_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(stories_dir.glob("*.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        chunks.append(Chunk(
            id=s["key"],
            text=f"{s['key']} {s['title']}\n{s['description']}\nRules: {', '.join(s.get('business_rules', []))}",
            source=f"stories/{path.name}",
            meta={"story": s["key"]},
        ))
        for ac in s["acceptance_criteria"]:
            chunks.append(Chunk(
                id=f"{s['key']}:{ac['id']}",
                text=f"{s['key']} {ac['id']}: {ac['text']}",
                source=f"stories/{path.name}#{ac['id']}",
                meta={"story": s["key"], "ac": ac["id"]},
            ))
    return chunks


def chunk_ux(ux: dict) -> list[Chunk]:
    chunks = []
    for frame, components in ux.get("frames", {}).items():
        lines = [f"- {c['kind']} '{c['label']}'" + (f" columns={c.get('columns')}" if c.get("columns") else "")
                 + (f" -> {c['navigates_to']}" if c.get("navigates_to") else "") for c in components]
        chunks.append(Chunk(
            id=f"figma:{frame}",
            text=f"Figma frame '{frame}' components:\n" + "\n".join(lines),
            source=f"figma/{_slug(frame)}",
            meta={"frame": frame},
        ))
    for v in ux.get("approved_variances", []):
        chunks.append(Chunk(
            id=f"figma-variance:{v.get('node_id')}",
            text=f"Approved variance on '{v.get('frame')}' for '{v.get('label')}': {json.dumps(v)}",
            source="figma/approved-variances",
        ))
    return chunks


def build_index(stories_dir: Path, knowledge_dir: Path, index_dir: Path, ux: dict | None,
                embedding_provider: str, embedding_model: str) -> VectorStore:
    chunks = chunk_stories(stories_dir)
    for md in sorted(knowledge_dir.glob("*.md")):
        chunks.extend(chunk_markdown(md))
    if ux:
        chunks.extend(chunk_ux(ux))
    embedder = get_embedder(embedding_provider, embedding_model)
    vectors = embedder.embed([c.text for c in chunks])
    store = VectorStore(index_dir)
    store.build(chunks, vectors, embedder.name)
    store.save()
    return store
