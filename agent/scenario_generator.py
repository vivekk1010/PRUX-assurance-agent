"""IntentModel -> AC-traceable ScenarioPlan in the constrained step language."""
import json
import re

from agent.models import IntentModel, ScenarioPlan, Step, Target, UXIntent
from llm import LLM, ReplayMissing
from rag.retriever import Retriever

CALCULATION_TERMS = {"word_count": "word", "reading_time": "reading time"}
HARD_CODED_NUMBER = re.compile(r"^\s*\d+\s*(min|mins|minutes?|words?)?\s*$", re.IGNORECASE)


def _is_calculation_ac(intent: IntentModel, ac_ids: list[str], term: str) -> bool:
    return any("calculation" in ac.checks and term in ac.text.lower() for ac in intent.acs if ac.id in ac_ids)


def generate_scenarios(intent: IntentModel, ux: UXIntent, retriever: Retriever, llm: LLM) -> tuple[ScenarioPlan, list[str]]:
    hits, seen = [], set()
    for ac in intent.acs:
        doc_types = {"business_rule", "test_data", "glossary"}
        if set(ac.checks) & {"api", "data", "calculation"}:
            doc_types.add("api_contract")
        if "figma" in ac.checks:
            doc_types.update({"figma_frame", "figma_variance"})
        for hit in retriever.search(
            f"{intent.story_key} {ac.id} {ac.text} {' '.join(ac.checks)}",
            k=5,
            filters={"doc_types": doc_types},
        ):
            if hit.chunk.id not in seen:
                seen.add(hit.chunk.id)
                hits.append(hit)
    if not hits:
        hits = retriever.search("UI contract controlled test data", k=8, source_prefix="knowledge_base")
    notes: list[str] = []
    try:
        plan = llm.structured(
            "generate_scenarios", intent.story_key,
            llm.prompt("generate_scenarios_system"),
            llm.prompt("generate_scenarios_user", story_key=intent.story_key, intent=intent.model_dump_json(indent=1),
                       ux=json.dumps({f: [c.model_dump(exclude_none=True) for c in cs] for f, cs in ux.frames.items()}, indent=1),
                       variances=json.dumps(ux.approved_variances, indent=1), context=Retriever.format(hits)),
            ScenarioPlan,
        )
    except ReplayMissing:
        return ScenarioPlan(scenarios=[]), ["No LLM key and no recorded scenarios for this story."]

    valid_ids = {ac.id for ac in intent.acs}
    ac_text = {ac.id: ac.text.lower() for ac in intent.acs}
    kinds = {c.kind for cs in ux.frames.values() for c in cs}
    kept = []
    for sc in plan.scenarios:
        sc.story_key = intent.story_key
        unknown = [a for a in sc.ac_ids if a not in valid_ids]
        if unknown or not sc.ac_ids:
            notes.append(f"Dropped {sc.id}: cites unknown AC ids {unknown or '[]'}")
            continue
        steps = []
        for i, step in enumerate(sc.steps, 1):
            if step.action == "check_calculation":
                term = CALCULATION_TERMS.get(step.name or "", step.name or "")
                if not any(term in ac_text[a] for a in sc.ac_ids):
                    notes.append(f"{sc.id} step {i}: removed check_calculation {step.name}; not mentioned by {sc.ac_ids}")
                    continue
            if step.action in {"expect_text", "expect_value"} and HARD_CODED_NUMBER.match(step.text or ""):
                notes.append(f"{sc.id} step {i}: removed hard-coded value '{step.text}'; derived numbers are verified by check_calculation")
                continue
            if step.target and step.target.label in kinds and step.text:
                notes.append(f"{sc.id} step {i}: target label '{step.target.label}' is a component kind; using text='{step.text}'")
                step.target = Target(text=step.text)
            steps.append(step)
        planned = {st.name for st in steps if st.action == "check_calculation"}
        for name, term in CALCULATION_TERMS.items():
            if name not in planned and any(term in ac_text[a] for a in sc.ac_ids) and _is_calculation_ac(intent, sc.ac_ids, term):
                notes.append(f"{sc.id}: added check_calculation {name}")
                steps.append(Step(action="check_calculation", name=name))
        sc.steps = steps
        kept.append(sc)
    plan.scenarios = kept
    return plan, notes
