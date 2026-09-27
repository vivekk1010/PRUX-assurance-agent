"""Interactive chat harness: ask questions in plain English; the LLM decides which assurance tools to run."""
import json
import os
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Callable, Optional

from agent.guardrails import mask_secrets
from agent.sources.jira import list_story_keys, load_story

MAX_TOOL_ROUNDS = 8

TOOLS = [
    {"name": "list_stories", "description": "List the Jira stories available for assurance with their acceptance criteria.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "show_story", "description": "Full text of one Jira story: description and acceptance criteria.",
     "parameters": {"type": "object", "properties": {"story_key": {"type": "string", "description": "e.g. BLOG-103"}},
                    "required": ["story_key"]}},
    {"name": "show_figma_design", "description": "Figma design from the Figma MCP server: frames, components, routes, "
                                                 "prototype flows and approved variances. Does not open a browser.",
     "parameters": {"type": "object", "properties": {"frame": {"type": "string", "description": "optional frame name, e.g. 'My Blogs'"}}}},
    {"name": "check_figma_conformance", "description": "Open every Figma frame's route on StageUI in a browser and compare "
                                                       "components and prototype flows with the design. Returns a verdict per frame with evidence.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "run_story_assurance", "description": "Run the full assurance loop (plan scenarios, drive the browser, check UI/API/DB/"
                                                   "calculations) for one or more stories. Returns a verdict per acceptance criterion with evidence.",
     "parameters": {"type": "object", "properties": {"story_keys": {"type": "array", "items": {"type": "string"}}},
                    "required": ["story_keys"]}},
    {"name": "get_results", "description": "Read verdicts from an earlier run (default: the latest run) without re-running.",
     "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}}}},
    {"name": "search_knowledge", "description": "Search the local RAG index: business rules, UI/API contract, test data, glossary, stories.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "open_report", "description": "Open the HTML report of a run (default: the latest run) in the default browser.",
     "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}}}},
]


def plain(text: str) -> str:
    """Terminal-friendly text: drop markdown emphasis, headings and link syntax; undo JSON-escaped backslashes."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)}: {m.group(2)}", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text.replace("\\\\", "\\").strip()


class ChatHarness:
    def __init__(self, settings, llm=None, log: Callable[[str], None] = print):
        from llm import LLM

        self.s = settings
        self.llm = llm or LLM.from_settings(settings)
        self.log = log
        self.messages: list[dict] = [{"role": "system", "content": self.llm.prompt("chat_system")}]
        self._stage = ExitStack()
        self._stage_up = False
        self._ux = None
        self._turn = 0

    def close(self) -> None:
        self._stage.close()

    # ---------- conversation ----------
    def ask(self, text: str) -> str:
        self._turn += 1
        self.messages.append({"role": "user", "content": text})
        for round_no in range(MAX_TOOL_ROUNDS):
            msg = self.llm._chat("chat", f"turn-{self._turn}-{round_no}", self.messages,
                                 tools=[{"type": "function", "function": t} for t in TOOLS])
            if not msg.tool_calls:
                answer = msg.content or ""
                self.messages.append({"role": "assistant", "content": answer})
                return plain(answer)
            self.messages.append({"role": "assistant", "content": msg.content,
                                  "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                self.log(f"  · {tc.function.name}({', '.join(f'{k}={v}' for k, v in args.items())})")
                output = self.call_tool(tc.function.name, args)
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
        return "Stopped after too many tool calls. Try a narrower question."

    def call_tool(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            result = handler(**args)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        return mask_secrets(json.dumps(result, default=str), [self.s.stage_password])

    # ---------- tools ----------
    def _tool_list_stories(self) -> list[dict]:
        out = []
        for key in list_story_keys(self.s.stories_dir):
            story = load_story(self.s.stories_dir, key)
            out.append({"key": key, "title": story.title, "acceptance_criteria": [f"{a.id}: {a.text}" for a in story.acceptance_criteria]})
        return out

    def _tool_show_story(self, story_key: str) -> dict:
        return load_story(self.s.stories_dir, story_key.upper()).model_dump()

    def _tool_show_figma_design(self, frame: Optional[str] = None) -> dict:
        from agent.sources.figma_client import fetch_ux_intent

        if self._ux is None:
            self._ux = fetch_ux_intent(None, with_images=True)
        ux = self._ux
        frames = {f: comps for f, comps in ux.frames.items() if not frame or f.lower() == frame.lower()}
        return {
            "file": ux.file_name,
            "frames": {f: {"node_id": ux.frame_nodes.get(f), "route": ux.frame_routes.get(f, {}).get("path"),
                           "design_image": ux.frame_images.get(f, {}).get("path"),
                           "components": [f"{c.node_id} {c.kind} '{c.label}'" + ("" if c.required else " (conditional)") for c in comps]}
                       for f, comps in frames.items()},
            "flows": ux.flows,
            "approved_variances": ux.approved_variances,
        }

    def _tool_check_figma_conformance(self) -> dict:
        return self._run([], figma=True)

    def _tool_run_story_assurance(self, story_keys: list[str]) -> dict:
        known = set(list_story_keys(self.s.stories_dir))
        keys = [k.upper() for k in story_keys]
        unknown = [k for k in keys if k not in known]
        if unknown:
            return {"error": f"unknown stories {unknown}", "known": sorted(known)}
        return self._run(keys, figma=False)

    def _tool_get_results(self, run_id: Optional[str] = None) -> dict:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            return {"error": "no runs yet"}
        return summarize(run_dir)

    def _tool_search_knowledge(self, query: str) -> list[dict]:
        from agent.cli import _retriever

        return [{"source": h.chunk.source, "score": round(h.score, 2), "text": h.chunk.text[:800]}
                for h in _retriever(self.s).search(query, k=4)]

    def _tool_open_report(self, run_id: Optional[str] = None) -> dict:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            return {"error": "no runs yet"}
        report = run_dir / "report.html"
        if hasattr(os, "startfile"):
            os.startfile(report)
        return {"opened": str(report)}

    # ---------- helpers ----------
    def _run(self, stories: list[str], figma: bool) -> dict:
        from agent.cli import run_stories, stage_session

        if not self._stage_up:
            self._stage_up = self._stage.enter_context(stage_session(self.s, start_stage=True))
            if not self._stage_up:
                return {"error": f"StageUI app not reachable at {self.s.stage_base_url}"}
        run_dir, _, _ = run_stories(self.s, stories, reset=True, figma=figma, log=lambda m: self.log(f"    {m.strip()}") if m.strip() else None)
        return summarize(run_dir)

    def _run_dir(self, run_id: Optional[str]) -> Optional[Path]:
        latest = self.s.runs_dir / "LATEST"
        run_id = run_id or (latest.read_text(encoding="utf-8").strip() if latest.exists() else None)
        return self.s.runs_dir / run_id if run_id and (self.s.runs_dir / run_id).exists() else None


def summarize(run_dir: Path) -> dict:
    """Compact, LLM-friendly view of results.json: verdicts, reasons and absolute evidence paths."""
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    path = lambda rel: str(run_dir / rel) if rel else None
    frames = [{
        "frame": f["frame"], "route": f["route"], "verdict": f["label"], "reason": f["rationale"],
        "problems": [f"{c['node_id']} {c['kind']} '{c['label']}': {c['status']} {c['detail']}".strip()
                     for c in f["components"] if c["status"] in {"missing", "mismatch", "approved_variance"}]
                    + [f"flow '{fl['trigger_label']}' -> {fl['to_frame']}: {fl['status']} {fl['detail']}".strip()
                       for fl in f["flows"] if fl["status"] != "ok"],
        "visual_review": (f.get("visual_review") or {}).get("summary"),
        "design_image": path(f.get("design_image")), "live_image": path(f.get("live_image")), "trace": path(f.get("trace_path")),
    } for f in data.get("figma_conformance", [])]
    stories = [{
        "story": s["story_key"], "title": s["title"], "verdict": s["label"], "recommendation": s.get("recommendation"),
        "acceptance_criteria": [{"id": v["ac_id"], "verdict": v["label"], "reason": v["rationale"][:600],
                                 "evidence": [path(e) for e in v["evidence"][:4]]} for v in s["ac_verdicts"]],
    } for s in data.get("stories", [])]
    return {"run_id": data["meta"]["run_id"], "report": str(run_dir / "report.html"), "figma_frames": frames, "stories": stories}


HELP = """Ask in plain English, for example:
  does the app match the figma design?
  test BLOG-103 and explain any failure
  is the tag filter implemented as designed?
  what should block sign-off?
Commands: /help  /headed (toggle visible browser)  /usage  /exit"""


def run_chat(settings, once: Optional[list[str]] = None) -> int:
    from llm import LLM

    llm = LLM.from_settings(settings)
    if not llm.is_live:
        print("Chat needs an LLM key (OPENAI_API_KEY or Azure settings in .env). "
              "Without one, use `python -m agent run` or `python -m agent conformance`.", file=sys.stderr)
        return 2
    stories = list_story_keys(settings.stories_dir)
    harness = ChatHarness(settings, llm)
    try:
        if once:
            for question in once:
                print(f"you> {question}")
                print(f"agent> {harness.ask(question)}\n")
            return 0
        print(f"PR-UX Assurance Agent · {settings.llm_provider} ({settings.llm_model}) · {len(stories)} stories: {', '.join(stories)}")
        print(HELP)
        while True:
            try:
                text = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text in {"/exit", "/quit", "exit", "quit"}:
                break
            if text == "/help":
                print(HELP)
                continue
            if text == "/headed":
                settings.headless = not settings.headless
                print(f"Browser {'hidden' if settings.headless else 'visible'} for the next runs.")
                continue
            if text == "/usage":
                u = llm.usage_summary()
                print(f"{u['calls']} LLM calls, {u['prompt_tokens']} prompt + {u['completion_tokens']} completion tokens")
                continue
            print(f"\nagent> {harness.ask(text)}")
    finally:
        harness.close()
    return 0
