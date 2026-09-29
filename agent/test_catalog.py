"""Durable, versioned test-plan catalog.

JSON is the canonical executable format. Spreadsheets are review projections
that are validated and imported back into this catalog.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from agent.models import TestCase, TestPlan


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "plan"


class TestCatalog:
    __test__ = False

    def __init__(self, root: Path):
        self.root = root

    def _story_dir(self, story_key: str) -> Path:
        return self.root / safe_slug(story_key)

    def next_version(self, story_key: str) -> int:
        versions = [p.stem.removeprefix("v") for p in self._story_dir(story_key).glob("v*.json")]
        return max((int(v) for v in versions if v.isdigit()), default=0) + 1

    def save(self, plan: TestPlan) -> Path:
        directory = self._story_dir(plan.story_key)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"v{plan.version}.json"
        if path.exists():
            raise FileExistsError(f"Test plan version already exists: {path}")
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        (directory / "LATEST").write_text(str(plan.version), encoding="utf-8")
        return path

    def replace_reviewed(self, plan: TestPlan) -> Path:
        """Persist review changes to an existing immutable generated version.

        Only review import uses this method; generation always creates a new
        version. The plan id and source hashes remain unchanged.
        """
        path = self._story_dir(plan.story_key) / f"v{plan.version}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, story_key: str, version: int | None = None) -> TestPlan:
        directory = self._story_dir(story_key)
        if version is None:
            latest = directory / "LATEST"
            if not latest.exists():
                raise FileNotFoundError(f"No test plan for {story_key}")
            version = int(latest.read_text(encoding="utf-8").strip())
        return TestPlan.model_validate_json((directory / f"v{version}.json").read_text(encoding="utf-8"))

    def list(self, story_key: str | None = None) -> list[TestPlan]:
        paths = (
            self._story_dir(story_key).glob("v*.json")
            if story_key
            else self.root.glob("*/v*.json")
        )
        return [TestPlan.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(paths)]

    def select(
        self,
        plans: Iterable[TestPlan],
        *,
        story: str | None = None,
        frame: str | None = None,
        feature: str | None = None,
        case_ids: set[str] | None = None,
        approved_only: bool = True,
    ) -> list[TestCase]:
        selected: list[TestCase] = []
        for plan in plans:
            if story and plan.story_key != story:
                continue
            for case in plan.cases:
                if approved_only and case.status != "APPROVED":
                    continue
                if frame and frame not in case.figma_frames:
                    continue
                if feature and feature not in case.feature_ids:
                    continue
                if case_ids and case.id not in case_ids:
                    continue
                selected.append(case)
        return selected

    @staticmethod
    def stale_sources(plan: TestPlan, root: Path) -> list[str]:
        stale = []
        for relative, expected in plan.source_hashes.items():
            path = root / relative
            if not path.exists() or file_hash(path) != expected:
                stale.append(relative)
        return stale


def plan_id(story_key: str, version: int, source_hashes: dict[str, str]) -> str:
    payload = json.dumps(source_hashes, sort_keys=True).encode()
    digest = hashlib.sha256(payload).hexdigest()[:10]
    return f"{safe_slug(story_key)}-v{version}-{digest}"
