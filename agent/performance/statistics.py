import math
import statistics
from collections import defaultdict

from agent.performance.models import (
    BudgetOutcome,
    MetricStatistics,
    PerformanceBaseline,
    PerformanceProfile,
    PerformanceSample,
    PerformanceSummary,
)


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate percentile of an empty sample")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def metric_statistics(values: list[float]) -> MetricStatistics:
    if not values:
        raise ValueError("metric requires at least one sample")
    mean = statistics.fmean(values)
    median = statistics.median(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    mad = statistics.median(abs(value - median) for value in values)
    return MetricStatistics(
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=mean,
        median=median,
        p75=percentile(values, 75),
        p90=percentile(values, 90),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        stddev=stddev,
        mad=mad,
        cv=(stddev / mean) if mean else 0.0,
    )


def summarize_samples(samples: list[PerformanceSample]) -> dict[str, MetricStatistics]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        grouped[sample.metric].append(sample.value)
    return {metric: metric_statistics(values) for metric, values in sorted(grouped.items())}


def _budget_outcome(
    budget,
    statistics_by_metric: dict[str, MetricStatistics],
    baseline: PerformanceBaseline | None,
) -> BudgetOutcome:
    current_stats = statistics_by_metric.get(budget.metric)
    baseline_stats = baseline.statistics.get(budget.metric) if baseline else None
    if current_stats is None:
        return BudgetOutcome(
            metric=budget.metric, statistic=budget.statistic, passed=False,
            severity=budget.severity, reason="metric was not collected",
            max_value=budget.max_value,
            max_regression_percent=budget.max_regression_percent,
        )
    actual = float(getattr(current_stats, budget.statistic))
    baseline_value = float(getattr(baseline_stats, budget.statistic)) if baseline_stats else None
    regression = None
    reasons = []
    passed = True
    if budget.max_value is not None and actual > budget.max_value:
        passed = False
        reasons.append(f"{actual:.2f} exceeds absolute budget {budget.max_value:.2f}")
    if budget.max_regression_percent is not None:
        if baseline_value is None:
            reasons.append("relative budget not evaluated (no matching baseline)")
        elif baseline_value == 0:
            regression = 0.0 if actual == 0 else math.inf
        else:
            regression = (actual - baseline_value) / baseline_value * 100.0
        if regression is not None and regression > budget.max_regression_percent:
            passed = False
            reasons.append(
                f"{regression:.2f}% regression exceeds {budget.max_regression_percent:.2f}%"
            )
    return BudgetOutcome(
        metric=budget.metric,
        statistic=budget.statistic,
        actual=actual,
        baseline=baseline_value,
        regression_percent=regression,
        max_value=budget.max_value,
        max_regression_percent=budget.max_regression_percent,
        passed=passed,
        severity=budget.severity,
        reason="; ".join(reasons) if reasons else "within budget",
    )


def build_summary(
    profile: PerformanceProfile,
    samples: list[PerformanceSample],
    environment_fingerprint: str,
    baseline: PerformanceBaseline | None = None,
    *,
    min_samples: int = 3,
    max_cv: float = 0.35,
) -> PerformanceSummary:
    statistics_by_metric = summarize_samples(samples)
    unstable = [
        metric for metric, values in statistics_by_metric.items()
        if values.count < min_samples or values.cv > max_cv
    ]
    outcomes = [
        _budget_outcome(budget, statistics_by_metric, baseline)
        for budget in profile.budgets
    ]
    failed = any(not outcome.passed and outcome.severity == "fail" for outcome in outcomes)
    warned = any(not outcome.passed and outcome.severity == "warn" for outcome in outcomes)
    if not statistics_by_metric:
        status = "NOT_MEASURED"
    elif failed:
        status = "FAIL"
    elif unstable:
        status = "UNSTABLE"
    elif warned:
        status = "WARN"
    else:
        status = "PASS"
    return PerformanceSummary(
        profile_id=profile.id,
        scope=profile.scope,
        status=status,
        environment_fingerprint=environment_fingerprint,
        statistics=statistics_by_metric,
        budgets=outcomes,
        unstable_metrics=unstable,
        baseline_id=baseline.id if baseline else None,
        baseline_statistics=baseline.statistics if baseline else {},
    )
