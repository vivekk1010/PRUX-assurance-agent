import json
from pathlib import Path

from agent.performance.models import PerformanceConfig, PerformanceProfile, PerformanceSelector


def _matches(selector: PerformanceSelector, context: dict[str, str | None]) -> bool:
    values = selector.model_dump(exclude_none=True)
    return all(context.get(key) == value for key, value in values.items())


class PerformanceProfileRegistry:
    def __init__(self, config: PerformanceConfig, source: Path | None = None):
        self.config = config
        self.source = source

    @classmethod
    def from_file(cls, path: Path) -> "PerformanceProfileRegistry":
        if not path.exists():
            return cls(PerformanceConfig(enabled=False), path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(PerformanceConfig.model_validate(payload), path)

    def by_id(self, profile_id: str) -> PerformanceProfile:
        matches = [profile for profile in self.config.profiles if profile.id == profile_id]
        if not matches:
            raise KeyError(f"Unknown performance profile '{profile_id}'")
        if len(matches) > 1:
            raise ValueError(f"Duplicate performance profile id '{profile_id}'")
        return matches[0]

    def resolve(
        self,
        *,
        story: str | None = None,
        test_case: str | None = None,
        feature: str | None = None,
        frame: str | None = None,
        page: str | None = None,
        component: str | None = None,
    ) -> list[PerformanceProfile]:
        if not self.config.enabled:
            return []
        context = {
            "story": story,
            "test_case": test_case,
            "feature": feature,
            "frame": frame,
            "page": page,
            "component": component,
        }
        candidates = [
            profile for profile in self.config.profiles
            if profile.enabled and _matches(profile.selector, context)
        ]
        selected: list[PerformanceProfile] = []
        for scope in ("page", "feature", "component", "api", "load"):
            scoped = [profile for profile in candidates if profile.scope == scope]
            if not scoped:
                continue
            maximum = max(profile.selector.specificity() for profile in scoped)
            winners = [profile for profile in scoped if profile.selector.specificity() == maximum]
            if len(winners) > 1:
                ids = ", ".join(profile.id for profile in winners)
                raise ValueError(f"Conflicting {scope} performance profiles: {ids}")
            selected.append(winners[0])
        return selected
