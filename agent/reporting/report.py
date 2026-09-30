import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from agent.guardrails import mask_secrets
from agent.models import FrameVerdict, StoryResult
from llm import LLM, ReplayMissing


class Recommendation(BaseModel):
    recommendation: str


def template_recommendation(result: StoryResult) -> str:
    if result.label == "PASS":
        return "All acceptance criteria are met with complete evidence. No action needed."
    lines = []
    for v in result.ac_verdicts:
        first = v.rationale.split(" (also ")[0]
        if v.label == "DEFECT":
            lines.append(f"Fix {v.ac_id}: behaviour contradicts the story. {first}")
        elif v.label == "GAP":
            lines.append(f"Implement {v.ac_id} against the story and approved UX. {first}")
        elif v.label == "RISK":
            lines.append(f"Human review for {v.ac_id}. {first}")
    return " ".join(lines)


def write_recommendation(result: StoryResult, llm: LLM) -> str:
    if result.label == "PASS" or not llm.is_live:
        return template_recommendation(result)
    try:
        verdicts = "\n".join(f"- {v.ac_id} {v.label}: {v.rationale[:400]}" for v in result.ac_verdicts)
        return llm.structured(
            "write_recommendation", result.story_key,
            llm.prompt("write_recommendation_system"),
            llm.prompt("write_recommendation_user", story_key=result.story_key, title=result.title,
                       label=result.label, verdicts=verdicts),
            Recommendation,
        ).recommendation
    except (ReplayMissing, ValueError):
        return template_recommendation(result)


def write_reports(run_dir: Path, results: list[StoryResult], meta: dict, secrets: list[str],
                  frames: list[FrameVerdict] | None = None, performance: dict | None = None) -> Path:
    payload = {"meta": meta, "figma_conformance": [f.model_dump() for f in frames or []],
               "stories": [r.model_dump() for r in results], "performance": performance}
    raw = mask_secrets(json.dumps(payload, indent=2, default=str), secrets)
    (run_dir / "results.json").write_text(raw, encoding="utf-8")

    data = json.loads(raw)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
    html = env.get_template("report.html.j2").render(
        meta=meta, stories=data["stories"], frames=data["figma_conformance"],
        evaluation=meta.get("evaluation"), performance=data.get("performance"),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    report = run_dir / "report.html"
    report.write_text(html, encoding="utf-8")
    return report
