from datetime import datetime, timezone
from pathlib import Path

from agent.performance.baselines import PerformanceBaselineStore
from agent.performance.exporters import export_otlp_json, write_prometheus_text
from agent.performance.integrations import (
    import_benchmarkdotnet,
    run_k6,
    run_lighthouse,
)
from agent.performance.models import PerformanceRun
from agent.performance.playwright_collector import PlaywrightPerformanceCollector
from agent.performance.profiles import PerformanceProfileRegistry
from agent.performance.statistics import build_summary
from agent.adapters import get_adapter


class PerformanceRunner:
    def __init__(self, settings, registry: PerformanceProfileRegistry | None = None, log=print):
        self.settings = settings
        self.registry = registry or PerformanceProfileRegistry.from_file(settings.performance_config)
        self.baselines = PerformanceBaselineStore(settings.performance_baselines_dir)
        self.log = log

    @property
    def enabled(self) -> bool:
        return bool(self.settings.performance_enabled or self.registry.config.enabled)

    def run(
        self,
        run_dir: Path,
        *,
        run_id: str,
        profile_ids: list[str] | None = None,
        context: dict[str, str | None] | None = None,
        force: bool = False,
    ) -> PerformanceRun:
        output = run_dir / "performance"
        output.mkdir(parents=True, exist_ok=True)
        result = PerformanceRun(run_id=run_id, enabled=self.enabled or force)
        if not result.enabled:
            result.warnings.append("performance measurement is disabled")
            self._save(result, run_dir)
            return result
        profiles = (
            [self.registry.by_id(profile_id) for profile_id in profile_ids]
            if profile_ids
            else self.registry.resolve(**(context or {}))
        )
        if not profiles:
            result.warnings.append("no enabled performance profiles matched")
            self._save(result, run_dir)
            return result

        for profile in profiles:
            profile_dir = output / profile.id
            profile_dir.mkdir(parents=True, exist_ok=True)
            samples = []
            fingerprint = "external-tool"
            if profile.integrations.playwright:
                self.log(f"  performance: {profile.id} ({profile.scope})")
                collected, fingerprint, tools = PlaywrightPerformanceCollector(
                    self.settings
                ).collect(profile, profile_dir)
                samples.extend(collected)
                result.tools.update(tools)

            external = []
            if profile.integrations.k6_browser or profile.integrations.k6_protocol:
                login_steps = [
                    step.model_dump(mode="json", exclude_none=True)
                    for step in get_adapter(self.settings).login_steps()
                ] if profile.integrations.k6_browser else []
                external.append(run_k6(
                    profile, self.settings.stage_base_url, profile_dir,
                    login_steps=login_steps,
                    target_user=self.settings.stage_user,
                    target_password=self.settings.stage_password,
                ))
            if profile.integrations.lighthouse:
                external.append(run_lighthouse(profile, self.settings.stage_base_url, profile_dir))
            if profile.integrations.benchmarkdotnet:
                external.append(import_benchmarkdotnet(profile, profile_dir))
            for integration in external:
                samples.extend(integration.samples)
                result.warnings.extend(integration.warnings)
                result.tools.update(integration.tools)

            baseline = self.baselines.load(profile.id)
            if baseline and baseline.environment_fingerprint != fingerprint:
                result.warnings.append(
                    f"{profile.id}: baseline environment differs; relative comparison was disabled"
                )
                baseline = None
            summary = build_summary(
                profile, samples, fingerprint, baseline,
                min_samples=self.settings.performance_min_samples,
                max_cv=self.settings.performance_max_cv,
            )
            require_baseline = (
                self.settings.performance_require_baseline
                or self.registry.config.require_baseline
            )
            if require_baseline and baseline is None and summary.status not in {"NOT_MEASURED", "FAIL"}:
                summary.status = "FAIL"
                result.warnings.append(f"{profile.id}: an approved matching baseline is required")
            result.samples.extend(samples)
            result.summaries.append(summary)
            (profile_dir / "summary.json").write_text(
                summary.model_dump_json(indent=2), encoding="utf-8"
            )

        result.completed_at = datetime.now(timezone.utc).isoformat()
        saved = self._save(result, run_dir)
        if any(profile.integrations.opentelemetry for profile in profiles):
            endpoint = self.registry.config.export.otlp_endpoint
            if endpoint:
                try:
                    export_otlp_json(result, endpoint)
                except Exception as exc:
                    result.warnings.append(f"OTLP export failed: {type(exc).__name__}: {exc}")
                    saved.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    @staticmethod
    def _save(result: PerformanceRun, run_dir: Path) -> Path:
        result.completed_at = result.completed_at or datetime.now(timezone.utc).isoformat()
        path = run_dir / "performance.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        write_prometheus_text(result, run_dir / "performance" / "metrics.prom")
        return path
