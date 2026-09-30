import re
from pathlib import Path

from agent.performance.models import PerformanceBaseline, PerformanceSummary


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "baseline"


class PerformanceBaselineStore:
    def __init__(self, root: Path):
        self.root = root

    def _profile_dir(self, profile_id: str) -> Path:
        return self.root / _slug(profile_id)

    def load(self, profile_id: str, baseline_id: str | None = None) -> PerformanceBaseline | None:
        directory = self._profile_dir(profile_id)
        if baseline_id is None:
            latest = directory / "LATEST"
            if not latest.exists():
                return None
            baseline_id = latest.read_text(encoding="utf-8").strip()
        path = directory / f"{_slug(baseline_id)}.json"
        if not path.exists():
            return None
        return PerformanceBaseline.model_validate_json(path.read_text(encoding="utf-8"))

    def promote(
        self,
        summary: PerformanceSummary,
        *,
        source_run_id: str,
        approved_by: str,
    ) -> tuple[PerformanceBaseline, Path]:
        if not approved_by.strip():
            raise ValueError("baseline promotion requires an approver")
        if summary.status in {"FAIL", "UNSTABLE", "NOT_MEASURED"}:
            raise ValueError(f"cannot promote performance result with status {summary.status}")
        if not summary.statistics:
            raise ValueError("cannot promote baseline without statistics")
        baseline_id = _slug(f"{source_run_id}-{summary.environment_fingerprint[:12]}")
        baseline = PerformanceBaseline(
            id=baseline_id,
            profile_id=summary.profile_id,
            approved_by=approved_by.strip(),
            source_run_id=source_run_id,
            environment_fingerprint=summary.environment_fingerprint,
            statistics=summary.statistics,
        )
        directory = self._profile_dir(summary.profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{baseline_id}.json"
        if path.exists():
            raise FileExistsError(f"baseline already exists: {path}")
        path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
        (directory / "LATEST").write_text(baseline_id, encoding="utf-8")
        return baseline, path
