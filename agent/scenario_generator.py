"""IntentModel -> AC-traceable ScenarioPlan in the constrained step language."""
import json

from agent.models import IntentModel, ScenarioPlan, UXIntent
from llm import LLM, ReplayMissing
from rag.retriever import Retriever


def generate_scenarios(intent: IntentModel, ux: UXIntent, retriever: Retriever, llm: LLM) -> tuple[ScenarioPlan, list[str]]:
    hits = retriever.search("UI contract data-testid pages API", k=2, source_prefix="knowledge_base/api_contract")
    hits += retriever.search("controlled test data users seeded posts tags filter expectations", k=10,
                             source_prefix="knowledge_base/test_data")
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
    kept = []
    for sc in plan.scenarios:
        sc.story_key = intent.story_key
        unknown = [a for a in sc.ac_ids if a not in valid_ids]
        if unknown or not sc.ac_ids:
            notes.append(f"Dropped {sc.id}: cites unknown AC ids {unknown or '[]'}")
            continue
        kept.append(sc)
    plan.scenarios = kept
    return plan, notes
