"""User entry point.

  python -m agent ingest                     build the local RAG index
  python -m agent search "reading time"      query the RAG index
  python -m agent figma                      list UX intent via the Figma MCP server
  python -m agent run --story BLOG-103       run assurance for one story
  python -m agent run --all                  run assurance for every story
  python -m agent graph                      print the orchestrator graph (mermaid)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx

from agent.config import ROOT, get_settings
from agent.sources.jira import list_story_keys, load_story


def cmd_ingest(settings) -> None:
    from agent.sources.figma_client import fetch_ux_intent
    from rag.ingest import build_index

    ux = fetch_ux_intent(None)
    expected_embedder = (
        f"openai:{settings.embedding_model}" if settings.embedding_provider == "openai" else "hashing-512"
    )
    if (settings.rag_index_dir / "chunks.json").exists():
        from rag.retriever import Retriever
        existing = Retriever(settings.rag_index_dir)
        freshness = existing.freshness(
            settings.stories_dir, settings.knowledge_dir,
            ux=ux.model_dump(), embedder_name=expected_embedder,
        )
        if freshness.fresh:
            print(f"RAG index is fresh ({len(existing.store.chunks)} chunks, {existing.store.embedder_name}).")
            return
    store = build_index(settings.stories_dir, settings.knowledge_dir, settings.rag_index_dir,
                        ux.model_dump(), settings.embedding_provider, settings.embedding_model)
    by_source: dict[str, int] = {}
    for c in store.chunks:
        top = c.source.split("/")[0]
        by_source[top] = by_source.get(top, 0) + 1
    print(f"Indexed {len(store.chunks)} chunks with {store.embedder_name} -> {settings.rag_index_dir}")
    for src, n in sorted(by_source.items()):
        print(f"  {src:15} {n}")


def _retriever(settings):
    from rag.retriever import Retriever

    if not (settings.rag_index_dir / "chunks.json").exists():
        print("RAG index missing; building it first.")
        cmd_ingest(settings)
    retriever = Retriever(
        settings.rag_index_dir,
        default_mode=settings.rag_mode,
        default_min_score=settings.rag_min_score,
        default_rrf_k=settings.rag_rrf_k,
    )
    freshness = retriever.freshness(settings.stories_dir, settings.knowledge_dir)
    if freshness.stale:
        print(f"Warning: RAG index is stale ({'; '.join(freshness.reasons)}). Run `python -m agent ingest`.")
    return retriever


def cmd_search(settings, query: str, k: int) -> None:
    for hit in _retriever(settings).search(query, k=k):
        print(f"{hit.score:5.2f}  {hit.chunk.source}\n       {hit.chunk.text.splitlines()[0][:100]}")


def cmd_figma(settings) -> None:
    from agent.sources.figma_client import fetch_ux_intent, list_tools

    print("MCP tools:", ", ".join(list_tools()))
    ux = fetch_ux_intent(None, with_images=True)
    print(f"File: {ux.file_name} (v{ux.version})")
    for frame, comps in ux.frames.items():
        route = ux.frame_routes.get(frame, {})
        print(f"\n[{frame}] node {ux.frame_nodes.get(frame)} · route {route.get('path')} · design {ux.frame_images.get(frame, {}).get('path')}")
        for c in comps:
            extra = f" -> {c.navigates_to}" if c.navigates_to else ""
            print(f"  {c.node_id:5} {c.kind:15} {c.label}{'' if c.required else ' (conditional)'}{extra}")
    print("\nApproved variances:")
    for v in ux.approved_variances:
        print(f"  {v['frame']} / {v['label']}: {v.get('allowed_labels') or v.get('allowed_kinds')} ({v['reason']})")


def _stage_up(settings) -> bool:
    from agent.adapters import get_adapter

    try:
        return httpx.get(get_adapter(settings).health_url, timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


@contextmanager
def stage_session(settings, start_stage: bool):
    """Yield True when StageUI is reachable; optionally start the reference StageUI app for the duration."""
    if _stage_up(settings):
        yield True
        return
    from agent.adapters import get_adapter

    adapter = get_adapter(settings)
    if not start_stage:
        print(f"Target app not reachable at {settings.stage_base_url}. Start it or pass --start-stage for a local adapter.")
        yield False
        return
    if not adapter.start_module:
        print(f"Adapter '{adapter.name}' cannot start an external target.", file=sys.stderr)
        yield False
        return
    adapter.reset()
    proc = subprocess.Popen([sys.executable, "-m", adapter.start_module], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if _stage_up(settings):
                break
            time.sleep(0.25)
        yield _stage_up(settings)
    finally:
        proc.terminate()


def cmd_run(settings, stories: list[str], reset: bool, start_stage: bool, figma: bool = True) -> int:
    with stage_session(settings, start_stage) as up:
        if not up:
            return 2
        run_dir, _, _ = run_stories(settings, stories, reset, figma=figma)
        evaluation = json.loads((run_dir / "eval.json").read_text(encoding="utf-8"))
        return 0 if evaluation["passed"] else 3


def cmd_generate(settings, stories: list[str], excel: bool) -> int:
    from agent.orchestrator import AssuranceAgent
    from agent.test_catalog import TestCatalog
    from agent.excel_io import export_plan

    retriever = _retriever(settings)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.runs_dir / f"{run_id}-planning"
    agent = AssuranceAgent(settings, run_dir, retriever, reset_stage=False)
    catalog = TestCatalog(settings.test_plans_dir)
    for key in stories:
        plan, path = agent.generate_test_plan(key, catalog)
        print(f"Generated {len(plan.cases)} draft test cases: {path}")
        if excel:
            book = export_plan(plan, path.with_suffix(".xlsx"), [settings.stage_password])
            print(f"Review workbook: {book}")
    return 0


def cmd_review(settings, action: str, story: str, file: str | None, version: int | None) -> int:
    from agent.excel_io import export_plan, import_review
    from agent.test_catalog import TestCatalog

    catalog = TestCatalog(settings.test_plans_dir)
    plan = catalog.load(story, version)
    path = Path(file) if file else settings.test_plans_dir / story / f"v{plan.version}.xlsx"
    if action == "export":
        export_plan(plan, path, [settings.stage_password])
        print(path)
        return 0
    story_model = load_story(settings.stories_dir, story)
    reviewed = import_review(
        path, plan, base_url=settings.stage_base_url,
        secrets=[settings.stage_password],
        valid_ac_ids={ac.id for ac in story_model.acceptance_criteria},
    )
    catalog.replace_reviewed(reviewed)
    approved = sum(case.status == "APPROVED" for case in reviewed.cases)
    print(f"Imported review for {reviewed.id}: {approved}/{len(reviewed.cases)} approved")
    return 0


def cmd_plans(settings, story: str | None) -> int:
    from agent.test_catalog import TestCatalog

    for plan in TestCatalog(settings.test_plans_dir).list(story):
        statuses: dict[str, int] = {}
        for case in plan.cases:
            statuses[case.status] = statuses.get(case.status, 0) + 1
        print(f"{plan.id}  {plan.story_key}  " + " ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    return 0


def cmd_performance(
    settings, action: str, *, profiles: list[str] | None = None,
    story: str | None = None, feature: str | None = None,
    page: str | None = None, component: str | None = None,
    run_id: str | None = None, approved_by: str | None = None,
    start_stage: bool = False,
) -> int:
    from agent.performance.baselines import PerformanceBaselineStore
    from agent.performance.models import PerformanceRun
    from agent.performance.profiles import PerformanceProfileRegistry

    registry = PerformanceProfileRegistry.from_file(settings.performance_config)
    if action == "list":
        print(
            f"performance {'enabled' if (settings.performance_enabled or registry.config.enabled) else 'disabled'} "
            f"({settings.performance_config})"
        )
        for profile in registry.config.profiles:
            print(
                f"{profile.id:28} scope={profile.scope:9} "
                f"{'enabled' if profile.enabled else 'disabled'}"
            )
        return 0
    if action == "promote":
        if not run_id or not profiles or len(profiles) != 1 or not approved_by:
            print("promote requires --run, exactly one --profile, and --approved-by", file=sys.stderr)
            return 2
        source_dir = settings.runs_dir / run_id
        evaluation_path = source_dir / "eval.json"
        if not evaluation_path.exists() or not json.loads(evaluation_path.read_text(encoding="utf-8")).get("passed"):
            print("baseline promotion requires a run with a passing eval.json", file=sys.stderr)
            return 2
        performance_path = source_dir / "performance.json"
        if not performance_path.exists():
            print(f"run {run_id} has no performance.json to promote", file=sys.stderr)
            return 2
        performance = PerformanceRun.model_validate_json(
            performance_path.read_text(encoding="utf-8")
        )
        summary = next((item for item in performance.summaries if item.profile_id == profiles[0]), None)
        if summary is None:
            print(f"profile {profiles[0]} was not measured in run {run_id}", file=sys.stderr)
            return 2
        baseline, path = PerformanceBaselineStore(settings.performance_baselines_dir).promote(
            summary, source_run_id=run_id, approved_by=approved_by
        )
        print(f"Promoted {baseline.id}: {path}")
        return 0

    from agent.performance.runner import PerformanceRunner
    from agent.reporting.evaluate_run import evaluate_run
    from agent.reporting.report import write_reports

    with stage_session(settings, start_stage) as up:
        if not up:
            return 2
        actual_run_id = datetime.now().strftime("%Y%m%d-%H%M%S-perf")
        run_dir = settings.runs_dir / actual_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        context = {
            "story": story, "feature": feature, "page": page, "component": component,
        }
        performance = PerformanceRunner(settings, registry).run(
            run_dir, run_id=actual_run_id, profile_ids=profiles,
            context=context, force=True,
        )
        meta = {
            "run_id": actual_run_id, "author": "Vivek Kaushik",
            "stage_base_url": settings.stage_base_url,
            "llm_provider": "none", "llm_model": "performance-only",
            "ux_source": "n/a", "embedder": "n/a",
        }
        payload = performance.model_dump(mode="json")
        write_reports(run_dir, [], meta, [], [], performance=payload)
        evaluation = evaluate_run(run_dir)
        meta["evaluation"] = evaluation
        report = write_reports(run_dir, [], meta, [], [], performance=payload)
        (settings.runs_dir / "LATEST").write_text(actual_run_id, encoding="utf-8")
        print(f"Performance report: {report}")
        fail_on_regression = (
            settings.performance_fail_on_regression
            and registry.config.fail_on_regression
        )
        return 3 if fail_on_regression and not performance.passed else (
            0 if evaluation["passed"] else 3
        )


def cmd_run_approved(
    settings, *, story: str | None, frame: str | None, feature: str | None,
    reset: bool, start_stage: bool, allow_stale: bool,
) -> int:
    from agent.orchestrator import AssuranceAgent
    from agent.reporting.report import write_reports
    from agent.test_catalog import TestCatalog

    catalog = TestCatalog(settings.test_plans_dir)
    if story:
        plans = [catalog.load(story)]
    else:
        keys = sorted({plan.story_key for plan in catalog.list()})
        plans = [catalog.load(key) for key in keys]
    selected = catalog.select(plans, story=story, frame=frame, feature=feature)
    if not selected:
        print("No approved test cases match the selector.", file=sys.stderr)
        return 2

    with stage_session(settings, start_stage) as up:
        if not up:
            return 2
        retriever = _retriever(settings)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = settings.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        agent = AssuranceAgent(settings, run_dir, retriever, reset_stage=reset)
        results, plan_ids = [], []
        selected_ids = {case.id for case in selected}
        for plan in plans:
            cases = [case for case in plan.cases if case.id in selected_ids]
            if not cases:
                continue
            stale = catalog.stale_sources(plan, ROOT)
            if stale and not allow_stale:
                print(f"Plan {plan.id} is stale ({', '.join(stale)}); regenerate or pass --allow-stale.", file=sys.stderr)
                return 2
            execution_plan = plan.model_copy(deep=True)
            execution_plan.cases = cases
            if allow_stale:
                execution_plan.source_versions = {}
            results.append(agent.execute_test_plan(execution_plan))
            plan_ids.append(plan.id)

        selector = {"story": story, "frame": frame, "feature": feature}
        from agent.performance.profiles import PerformanceProfileRegistry
        from agent.performance.runner import PerformanceRunner

        registry = PerformanceProfileRegistry.from_file(settings.performance_config)
        performance = None
        if (
            (settings.performance_enabled or registry.config.enabled)
            and (settings.performance_auto_run or registry.config.auto_run_with_approved_tests)
        ):
            performance = PerformanceRunner(settings, registry).run(
                run_dir, run_id=run_id,
                context={"story": story, "frame": frame, "feature": feature},
            )
        performance_payload = performance.model_dump(mode="json") if performance else None
        meta = {
            "run_id": run_id, "author": "Vivek Kaushik", "stage_base_url": settings.stage_base_url,
            "llm_provider": settings.llm_provider, "llm_model": settings.llm_model,
            "ux_source": f"figma-mcp ({os.getenv('FIGMA_SOURCE', 'fixture')})",
            "embedder": retriever.store.embedder_name, "figma_llm_usage": {},
            "approved_plan_ids": plan_ids, "selector": selector,
            "approved_cases": [
                {
                    "id": case.id, "story_key": case.story_key, "ac_ids": case.ac_ids,
                    "feature_ids": case.feature_ids, "figma_frames": case.figma_frames,
                    "citations": [citation.source for citation in case.citations],
                }
                for case in selected
            ],
            "plan_sources_fresh": True,
        }
        report = write_reports(
            run_dir, results, meta, [settings.stage_password], [],
            performance=performance_payload,
        )
        from agent.adapters import get_adapter
        from agent.reporting.evaluate_run import evaluate_run
        evaluation = evaluate_run(run_dir, secrets=get_adapter(settings).secrets())
        meta["evaluation"] = evaluation
        report = write_reports(
            run_dir, results, meta, get_adapter(settings).secrets(), [],
            performance=performance_payload,
        )
        from agent.excel_io import append_execution_results
        for plan in plans:
            if plan.id not in plan_ids:
                continue
            workbook = settings.test_plans_dir / plan.story_key / f"v{plan.version}.xlsx"
            append_execution_results(
                workbook,
                [result for result in results if result.story_key == plan.story_key],
                evaluation,
                get_adapter(settings).secrets(),
                performance_payload,
            )
        (settings.runs_dir / "LATEST").write_text(run_id, encoding="utf-8")
        print(f"Report: {report}")
    return 0 if evaluation["passed"] else 3


def run_stories(settings, stories: list[str], reset: bool = True, log=print, figma: bool = True):
    """Run story assurance and Figma conformance. Returns (run_dir, story_results, frame_verdicts)."""
    from agent.conformance import run_conformance
    from agent.orchestrator import AssuranceAgent
    from agent.reporting.report import write_reports
    from agent.sources.figma_client import fetch_ux_intent
    from llm import LLM

    retriever = _retriever(settings)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    agent = AssuranceAgent(settings, run_dir, retriever, reset_stage=reset, log=log)
    log(f"Run {run_id} | LLM={settings.llm_provider} ({settings.llm_model}) | StageUI={settings.stage_base_url}")

    results = []
    for key in stories:
        log(f"\n▶ {key}")
        result = agent.run_story(key)
        results.append(result)
        marks = " ".join(f"{v.ac_id}={v.label}" for v in result.ac_verdicts)
        log(f"  ⇒ {key}: {result.label}  {marks}  ({result.duration_ms / 1000:.1f}s)")

    frames, figma_usage = [], {}
    if figma:
        log("\n▶ Figma conformance")
        if reset:
            from agent.adapters import get_adapter
            get_adapter(settings).reset()
        llm = LLM.from_settings(settings)
        frames = run_conformance(settings, fetch_ux_intent(None, with_images=True), llm, run_dir, log=log)
        figma_usage = llm.usage_summary()

    meta = {"run_id": run_id, "author": "Vivek Kaushik", "stage_base_url": settings.stage_base_url,
            "llm_provider": settings.llm_provider, "llm_model": settings.llm_model if settings.llm_provider != "replay" else "replay",
            "ux_source": f"figma-mcp ({os.getenv('FIGMA_SOURCE', 'fixture')})",
            "embedder": retriever.store.embedder_name, "figma_llm_usage": figma_usage}
    report = write_reports(run_dir, results, meta, [settings.stage_password], frames)
    from agent.adapters import get_adapter
    from agent.reporting.evaluate_run import evaluate_run
    evaluation = evaluate_run(run_dir, secrets=get_adapter(settings).secrets())
    meta["evaluation"] = evaluation
    report = write_reports(run_dir, results, meta, get_adapter(settings).secrets(), frames)
    (settings.runs_dir / "LATEST").write_text(run_id, encoding="utf-8")
    log(f"\nReport: {report}")
    return run_dir, results, frames


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description="StageUI Requirement & UX Assurance Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="build the local RAG index")
    p_search = sub.add_parser("search", help="query the RAG index")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    sub.add_parser("figma", help="show UX intent from the Figma MCP server")
    sub.add_parser("graph", help="print orchestrator graph as mermaid")
    p_run = sub.add_parser("run", help="run assurance")
    group = p_run.add_mutually_exclusive_group(required=True)
    group.add_argument("--story", action="append", help="story key, repeatable")
    group.add_argument("--all", action="store_true")
    p_run.add_argument("--no-reset", action="store_true", help="do not reset StageUI data before each story")
    p_run.add_argument("--start-stage", action="store_true", help="start the reference StageUI app if it is not running")
    p_run.add_argument("--headed", action="store_true", help="show the browser")
    p_run.add_argument("--no-figma", action="store_true", help="skip the Figma conformance pass")
    p_generate = sub.add_parser("generate", help="generate draft test plans without executing them")
    generate_group = p_generate.add_mutually_exclusive_group(required=True)
    generate_group.add_argument("--story", action="append", help="story key, repeatable")
    generate_group.add_argument("--all", action="store_true")
    p_generate.add_argument("--excel", action="store_true", help="also create a human-review workbook")
    p_review = sub.add_parser("review", help="export or import a test-plan review workbook")
    p_review.add_argument("action", choices=["export", "import"])
    p_review.add_argument("--story", required=True)
    p_review.add_argument("--version", type=int)
    p_review.add_argument("--file")
    p_plans = sub.add_parser("plans", help="list generated test plans")
    p_plans.add_argument("--story")
    p_approved = sub.add_parser("run-approved", help="execute only approved test cases")
    approved_group = p_approved.add_mutually_exclusive_group(required=True)
    approved_group.add_argument("--story")
    approved_group.add_argument("--frame")
    approved_group.add_argument("--feature")
    p_approved.add_argument("--start-stage", action="store_true")
    p_approved.add_argument("--no-reset", action="store_true")
    p_approved.add_argument("--allow-stale", action="store_true")
    p_conf = sub.add_parser("conformance", help="Figma conformance only: one verdict per design frame")
    p_conf.add_argument("--start-stage", action="store_true")
    p_conf.add_argument("--headed", action="store_true")
    p_chat = sub.add_parser("chat", help="chat with the agent in plain English; it decides which checks to run")
    p_chat.add_argument("--headed", action="store_true", help="show the browser during checks")
    p_chat.add_argument("--once", action="append", metavar="QUESTION", help="ask one question and exit (repeatable)")
    p_perf = sub.add_parser("performance", help="run or manage configurable performance profiles")
    p_perf.add_argument("action", choices=["list", "run", "promote"])
    p_perf.add_argument("--profile", action="append", dest="profiles")
    perf_selector = p_perf.add_mutually_exclusive_group()
    perf_selector.add_argument("--story")
    perf_selector.add_argument("--feature")
    perf_selector.add_argument("--page")
    perf_selector.add_argument("--component")
    p_perf.add_argument("--run", dest="run_id")
    p_perf.add_argument("--approved-by")
    p_perf.add_argument("--start-stage", action="store_true")
    p_perf.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.cmd in {"run", "run-approved", "conformance", "chat"} or (
        args.cmd == "performance" and args.action == "run"
    ):
        from agent.adapters import get_adapter
        adapter = get_adapter(settings)
        if settings.target_auth_method == "form" and adapter.login_steps() and not settings.stage_password:
            print("TARGET_PASSWORD (or legacy STAGE_PASSWORD) is not set. Add it to .env.", file=sys.stderr)
            return 2
    if args.cmd == "ingest":
        cmd_ingest(settings)
    elif args.cmd == "search":
        cmd_search(settings, args.query, args.k)
    elif args.cmd == "figma":
        cmd_figma(settings)
    elif args.cmd == "graph":
        from agent.orchestrator import AssuranceAgent
        print(AssuranceAgent.__new__(AssuranceAgent)._build_graph().get_graph().draw_mermaid())
    elif args.cmd == "generate":
        stories = list_story_keys(settings.stories_dir) if args.all else args.story
        return cmd_generate(settings, stories, args.excel)
    elif args.cmd == "review":
        return cmd_review(settings, args.action, args.story, args.file, args.version)
    elif args.cmd == "plans":
        return cmd_plans(settings, args.story)
    elif args.cmd == "performance":
        if args.headed:
            settings.headless = False
        return cmd_performance(
            settings, args.action, profiles=args.profiles,
            story=args.story, feature=args.feature, page=args.page,
            component=args.component, run_id=args.run_id,
            approved_by=args.approved_by, start_stage=args.start_stage,
        )
    elif args.cmd == "run-approved":
        return cmd_run_approved(
            settings, story=args.story, frame=args.frame, feature=args.feature,
            reset=not args.no_reset, start_stage=args.start_stage, allow_stale=args.allow_stale,
        )
    elif args.cmd == "run":
        if args.headed:
            settings.headless = False
        stories = list_story_keys(settings.stories_dir) if args.all else args.story
        return cmd_run(settings, stories, reset=not args.no_reset, start_stage=args.start_stage, figma=not args.no_figma)
    elif args.cmd == "conformance":
        if args.headed:
            settings.headless = False
        return cmd_run(settings, [], reset=True, start_stage=args.start_stage, figma=True)
    elif args.cmd == "chat":
        from agent.chat import run_chat

        if args.headed:
            settings.headless = False
        return run_chat(settings, args.once)
    return 0
