"""User entry point.

  python -m agent ingest                     build the local RAG index
  python -m agent search "reading time"      query the RAG index
  python -m agent figma                      list UX intent via the Figma MCP server
  python -m agent run --story BLOG-103       run assurance for one story
  python -m agent run --all                  run assurance for every story
  python -m agent graph                      print the orchestrator graph (mermaid)
"""
import argparse
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime

import httpx

from agent.config import ROOT, get_settings
from agent.sources.jira import list_story_keys


def cmd_ingest(settings) -> None:
    from agent.sources.figma_client import fetch_ux_intent
    from rag.ingest import build_index

    ux = fetch_ux_intent(None)
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
    return Retriever(settings.rag_index_dir)


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
    try:
        return httpx.get(f"{settings.stage_base_url}/login", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@contextmanager
def stage_session(settings, start_stage: bool):
    """Yield True when Stage is reachable; optionally start the reference Stage app for the duration."""
    if _stage_up(settings):
        yield True
        return
    if not start_stage:
        print(f"Stage app not reachable at {settings.stage_base_url}. Start it with `python -m stage_app` "
              "or pass --start-stage.")
        yield False
        return
    subprocess.run([sys.executable, "-m", settings.stage_reset_module], cwd=ROOT, check=True)
    proc = subprocess.Popen([sys.executable, "-m", "stage_app"], cwd=ROOT,
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
        run_stories(settings, stories, reset, figma=figma)
        return 0


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
    log(f"Run {run_id} | LLM={settings.llm_provider} ({settings.llm_model}) | Stage={settings.stage_base_url}")

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
            subprocess.run([sys.executable, "-m", settings.stage_reset_module], cwd=ROOT, check=True, capture_output=True)
        llm = LLM.from_settings(settings)
        frames = run_conformance(settings, fetch_ux_intent(None, with_images=True), llm, run_dir, log=log)
        figma_usage = llm.usage_summary()

    meta = {"run_id": run_id, "author": "Vivek Kaushik", "stage_base_url": settings.stage_base_url,
            "llm_provider": settings.llm_provider, "llm_model": settings.llm_model if settings.llm_provider != "replay" else "replay",
            "ux_source": f"figma-mcp ({os.getenv('FIGMA_SOURCE', 'fixture')})",
            "embedder": retriever.store.embedder_name, "figma_llm_usage": figma_usage}
    report = write_reports(run_dir, results, meta, [settings.stage_password], frames)
    (settings.runs_dir / "LATEST").write_text(run_id, encoding="utf-8")
    log(f"\nReport: {report}")
    return run_dir, results, frames


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Stage Requirement & UX Assurance Agent")
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
    p_run.add_argument("--no-reset", action="store_true", help="do not reset Stage data before each story")
    p_run.add_argument("--start-stage", action="store_true", help="start the reference Stage app if it is not running")
    p_run.add_argument("--headed", action="store_true", help="show the browser")
    p_run.add_argument("--no-figma", action="store_true", help="skip the Figma conformance pass")
    p_conf = sub.add_parser("conformance", help="Figma conformance only: one verdict per design frame")
    p_conf.add_argument("--start-stage", action="store_true")
    p_conf.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.cmd in {"run", "conformance"} and not settings.stage_password:
        print("STAGE_PASSWORD is not set. Add it to .env (see .env.example).", file=sys.stderr)
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
    elif args.cmd == "run":
        if args.headed:
            settings.headless = False
        stories = list_story_keys(settings.stories_dir) if args.all else args.story
        return cmd_run(settings, stories, reset=not args.no_reset, start_stage=args.start_stage, figma=not args.no_figma)
    elif args.cmd == "conformance":
        if args.headed:
            settings.headless = False
        return cmd_run(settings, [], reset=True, start_stage=args.start_stage, figma=True)
    return 0
