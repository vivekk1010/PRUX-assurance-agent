"""Stable content hashes and source-freshness checks for local RAG indexes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def hash_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def source_files(stories_dir: Path, knowledge_dir: Path) -> list[Path]:
    return sorted(stories_dir.glob("*.json")) + sorted(
        path for path in knowledge_dir.iterdir() if path.is_file() and path.suffix in {".md", ".json"}
    )


def source_hashes(
    stories_dir: Path, knowledge_dir: Path, root: Path | None = None
) -> dict[str, str]:
    root = root or _common_root(stories_dir, knowledge_dir)
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): hash_file(path)
        for path in source_files(stories_dir, knowledge_dir)
    }


def ux_hash(ux: dict[str, Any] | None) -> str | None:
    if not ux:
        return None
    stable_ux = {
        key: ux.get(key)
        for key in (
            "file_name", "version", "frames", "flows", "approved_variances",
            "frame_nodes", "frame_routes", "features",
        )
        if key in ux
    }
    serialized = json.dumps(stable_ux, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_text(serialized)


def build_manifest(
    stories_dir: Path,
    knowledge_dir: Path,
    *,
    chunks: Iterable[Any],
    embedder_name: str,
    ux: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _common_root(stories_dir, knowledge_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "embedder": embedder_name,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "root": root.as_posix(),
        "files": source_hashes(stories_dir, knowledge_dir, root),
        "ux_hash": ux_hash(ux),
        "ux_version": (ux or {}).get("version"),
        "chunk_count": sum(1 for _ in chunks),
    }


def load_manifest(index_dir: Path) -> dict[str, Any] | None:
    path = index_dir / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class FreshnessReport:
    fresh: bool
    reasons: tuple[str, ...] = ()

    @property
    def stale(self) -> bool:
        return not self.fresh


def check_freshness(
    index_dir: Path,
    stories_dir: Path,
    knowledge_dir: Path,
    *,
    ux: dict[str, Any] | None = None,
    embedder_name: str | None = None,
) -> FreshnessReport:
    manifest = load_manifest(index_dir)
    if manifest is None:
        return FreshnessReport(False, ("manifest missing",))

    reasons: list[str] = []
    root = _common_root(stories_dir, knowledge_dir)
    current_files = source_hashes(stories_dir, knowledge_dir, root)
    if manifest.get("files") != current_files:
        old = manifest.get("files", {})
        changed = sorted(
            path for path in set(old) | set(current_files) if old.get(path) != current_files.get(path)
        )
        reasons.append("source files changed: " + ", ".join(changed))
    if ux is not None and manifest.get("ux_hash") != ux_hash(ux):
        reasons.append("Figma UX source changed")
    if embedder_name is not None and manifest.get("embedder") != embedder_name:
        reasons.append("embedder changed")
    return FreshnessReport(not reasons, tuple(reasons))


def is_stale(
    index_dir: Path,
    stories_dir: Path,
    knowledge_dir: Path,
    *,
    ux: dict[str, Any] | None = None,
    embedder_name: str | None = None,
) -> bool:
    return check_freshness(
        index_dir, stories_dir, knowledge_dir, ux=ux, embedder_name=embedder_name
    ).stale


def _common_root(stories_dir: Path, knowledge_dir: Path) -> Path:
    stories_parent = stories_dir.resolve().parent
    knowledge_parent = knowledge_dir.resolve().parent
    return stories_parent if stories_parent == knowledge_parent else Path(
        __import__("os").path.commonpath([stories_dir.resolve(), knowledge_dir.resolve()])
    )
