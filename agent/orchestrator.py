"""LangGraph orchestration of one assurance run per story."""
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.classifier import classify, story_label
from agent.config import ROOT, Settings
from agent.executor import run_scenario
from agent.intent_builder import build_intent, retrieve_context
from agent.models import IntentModel, ScenarioPlan, ScenarioResult, Story, StoryResult, UXIntent, ACVerdict
from agent.reporting.report import write_recommendation
from agent.scenario_generator import generate_scenarios
from agent.sources.figma_client import fetch_ux_intent
from agent.sources.jira import load_story
from llm import LLM
from rag.retriever import Retriever


class AssuranceState(TypedDict, total=False):
    story_key: str
    story: Story
    ux: UXIntent
    hits: list
    intent: IntentModel
    plan: ScenarioPlan
    scenario_results: list[ScenarioResult]
    verdicts: list[ACVerdict]
    result: StoryResult
    notes: list[str]
    error: Optional[str]


class AssuranceAgent:
    def __init__(self, settings: Settings, run_dir: Path, retriever: Retriever, reset_stage: bool = True, log=print):
        self.s = settings
        self.run_dir = run_dir
        self.retriever = retriever
        self.reset_stage = reset_stage
        self.log = log
        self.graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(AssuranceState)
        g.add_node("reset_stage_data", self.reset_stage_data)
        g.add_node("load_story", self.load_story)
        g.add_node("load_ux_intent", self.load_ux_intent)
        g.add_node("retrieve_context", self.retrieve_context)
        g.add_node("build_intent", self.build_intent)
        g.add_node("generate_scenarios", self.generate_scenarios)
        g.add_node("execute_scenarios", self.execute_scenarios)
        g.add_node("classify", self.classify)
        g.add_node("report", self.report)

        g.add_edge(START, "reset_stage_data")
        g.add_edge("reset_stage_data", "load_story")
        g.add_conditional_edges("load_story", lambda st: "report" if st.get("error") else "load_ux_intent",
                                ["load_ux_intent", "report"])
        g.add_conditional_edges("load_ux_intent", lambda st: "report" if st.get("error") else "retrieve_context",
                                ["retrieve_context", "report"])
        g.add_edge("retrieve_context", "build_intent")
        g.add_edge("build_intent", "generate_scenarios")
        g.add_edge("generate_scenarios", "execute_scenarios")
        g.add_edge("execute_scenarios", "classify")
        g.add_edge("classify", "report")
        g.add_edge("report", END)
        return g.compile()

    def story_dir(self, key: str) -> Path:
        path = self.run_dir / key
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ---------- nodes ----------
    def reset_stage_data(self, st: AssuranceState) -> dict:
        if self.reset_stage:
            subprocess.run([sys.executable, "-m", self.s.stage_reset_module], cwd=ROOT, check=True, capture_output=True)
            self.log("  • Stage data reset to controlled seed")
        return {"notes": []}

    def load_story(self, st: AssuranceState) -> dict:
        try:
            story = load_story(self.s.stories_dir, st["story_key"])
            self.log(f"  • Loaded story: {story.title} ({len(story.acceptance_criteria)} ACs)")
            return {"story": story}
        except Exception as exc:
            return {"error": f"Jira ingestion failed: {exc}"}

    def load_ux_intent(self, st: AssuranceState) -> dict:
        try:
            ux = fetch_ux_intent(st["story_key"])
            self.log(f"  • Figma MCP: frames {list(ux.frames)}, {len(ux.approved_variances)} approved variance(s)")
            return {"ux": ux}
        except Exception as exc:
            return {"error": f"Figma MCP ingestion failed: {exc}"}

    def retrieve_context(self, st: AssuranceState) -> dict:
        hits = retrieve_context(st["story"], self.retriever)
        self.log(f"  • RAG: {len(hits)} context chunks ({', '.join(h.chunk.source.split('/')[-1] for h in hits[:4])}...)")
        return {"hits": hits}

    def build_intent(self, st: AssuranceState) -> dict:
        intent, method = build_intent(st["story"], st["ux"], st["hits"], self.llm)
        (self.story_dir(st["story_key"]) / "intent.json").write_text(intent.model_dump_json(indent=2), encoding="utf-8")
        flagged = [a.id for a in intent.acs if a.ambiguous]
        self.log(f"  • Intent built via {method}" + (f"; ambiguous ACs: {flagged}" if flagged else ""))
        return {"intent": intent}

    def generate_scenarios(self, st: AssuranceState) -> dict:
        plan, notes = generate_scenarios(st["intent"], st["ux"], self.retriever, self.llm)
        (self.story_dir(st["story_key"]) / "scenarios.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        self.log(f"  • {len(plan.scenarios)} scenarios generated" + (f" ({'; '.join(notes)})" if notes else ""))
        return {"plan": plan, "notes": st.get("notes", []) + notes}

    def execute_scenarios(self, st: AssuranceState) -> dict:
        results = []
        for sc in st["plan"].scenarios:
            res = run_scenario(self.s, st["ux"], self.llm, sc, self.story_dir(st["story_key"]) / sc.id)
            worst = next((s.status for s in res.steps if s.status not in {"ok", "skipped"}), "ok")
            self.log(f"    - {sc.id} [{', '.join(sc.ac_ids)}] {sc.title}: {worst} ({res.duration_ms} ms)")
            results.append(res)
        return {"scenario_results": results}

    def classify(self, st: AssuranceState) -> dict:
        return {"verdicts": classify(st["intent"], st["scenario_results"], self.run_dir)}

    def report(self, st: AssuranceState) -> dict:
        key = st["story_key"]
        if st.get("error"):
            story = st.get("story")
            result = StoryResult(story_key=key, title=story.title if story else key, label="RISK", ac_verdicts=[],
                                 error=st["error"], recommendation="Fix ingestion and re-run.")
        else:
            verdicts = st["verdicts"]
            result = StoryResult(
                story_key=key, title=st["story"].title, label=story_label(verdicts), ac_verdicts=verdicts,
                scenario_results=st["scenario_results"],
                intent_path=f"{key}/intent.json", scenarios_path=f"{key}/scenarios.json",
            )
            result.recommendation = write_recommendation(result, self.llm)
        return {"result": result}

    # ---------- entry ----------
    def run_story(self, key: str) -> StoryResult:
        self.llm = LLM.from_settings(self.s)
        start = time.perf_counter()
        final = self.graph.invoke({"story_key": key})
        result: StoryResult = final["result"]
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        result.llm_usage = self.llm.usage_summary()
        (self.story_dir(key) / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()
