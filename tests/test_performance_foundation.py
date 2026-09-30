import json

import pytest

from agent.performance.baselines import PerformanceBaselineStore
from agent.performance.models import (
    PerformanceBaseline,
    PerformanceConfig,
    PerformanceProfile,
    PerformanceSample,
    PerformanceSelector,
)
from agent.performance.profiles import PerformanceProfileRegistry
from agent.performance.statistics import build_summary, metric_statistics, percentile


def profile(**overrides):
    data = {
        "id": "page-home",
        "scope": "page",
        "selector": {"page": "/home"},
        "path": "/home",
        "browser": {"iterations": 3, "cache_modes": ["warm"]},
        "budgets": [
            {"metric": "nav.wall_ms.warm", "statistic": "p95", "max_value": 300}
        ],
    }
    data.update(overrides)
    return PerformanceProfile.model_validate(data)


def samples(values=(100.0, 120.0, 140.0)):
    return [
        PerformanceSample(
            profile_id="page-home", measurement_id="nav",
            metric="nav.wall_ms.warm", value=value, iteration=index, cache_mode="warm",
        )
        for index, value in enumerate(values)
    ]


def test_statistics_include_distribution_and_variance():
    stats = metric_statistics([100, 120, 140])
    assert stats.median == 120
    assert stats.p95 == pytest.approx(138)
    assert stats.mad == 20
    assert percentile([10], 99) == 10


def test_budget_and_relative_baseline_evaluation():
    current_profile = profile(budgets=[{
        "metric": "nav.wall_ms.warm", "statistic": "p95",
        "max_value": 300, "max_regression_percent": 10,
    }])
    baseline_summary = build_summary(current_profile, samples((100, 100, 100)), "same")
    baseline = PerformanceBaseline(
        id="base", profile_id=current_profile.id, approved_by="qa",
        source_run_id="run-1", environment_fingerprint="same",
        statistics=baseline_summary.statistics,
    )
    summary = build_summary(current_profile, samples((115, 120, 125)), "same", baseline)
    assert summary.status == "FAIL"
    assert summary.budgets[0].regression_percent > 10


def test_profile_resolution_prefers_specific_selector(tmp_path):
    config = PerformanceConfig(
        enabled=True,
        profiles=[
            profile(id="default", selector={}, path="/home"),
            profile(id="feature", scope="feature", selector={"feature": "search"}, steps=[{"action": "goto"}]),
            profile(id="component", scope="component", selector={"component": "box"}, path="/home"),
        ],
    )
    registry = PerformanceProfileRegistry(config)
    resolved = registry.resolve(feature="search", component="box", page="/home")
    assert {item.id for item in resolved} == {"default", "feature", "component"}


def test_conflicting_profile_resolution_fails():
    config = PerformanceConfig(
        enabled=True,
        profiles=[profile(id="one"), profile(id="two")],
    )
    with pytest.raises(ValueError, match="Conflicting page"):
        PerformanceProfileRegistry(config).resolve(page="/home")


def test_disabled_missing_registry_is_empty(tmp_path):
    registry = PerformanceProfileRegistry.from_file(tmp_path / "missing.json")
    assert registry.resolve(page="/home") == []


def test_baseline_promotion_is_human_controlled_and_immutable(tmp_path):
    summary = build_summary(profile(), samples(), "env")
    store = PerformanceBaselineStore(tmp_path)
    with pytest.raises(ValueError, match="approver"):
        store.promote(summary, source_run_id="run-1", approved_by="")
    baseline, path = store.promote(summary, source_run_id="run-1", approved_by="Vivek")
    assert path.exists()
    assert store.load("page-home").id == baseline.id
    with pytest.raises(FileExistsError):
        store.promote(summary, source_run_id="run-1", approved_by="Vivek")
