"""Story + UX intent + retrieved context -> structured expected-behavior record (IntentModel)."""
import json
import re

from agent.models import ACIntent, IntentModel, Story, UXIntent
from llm import LLM, ReplayMissing
from rag.retriever import Retriever
from rag.store import Hit

VAGUE = re.compile(
    r"\b(fast|quick(ly)?|slow|user[- ]friendly|intuitive|nice|easy|good|responsive|appropriate|reasonable|smooth|clean)\b",
    re.IGNORECASE,
)


def retrieve_context(story: Story, retriever: Retriever, k_per_query: int = 3, limit: int = 10) -> list[Hit]:
    queries = [story.title] + [ac.text for ac in story.acceptance_criteria] + story.business_rules
    seen, hits = set(), []
    for q in queries:
        for hit in retriever.search(q, k=k_per_query, source_prefix="knowledge_base"):
            if hit.chunk.id not in seen:
                seen.add(hit.chunk.id)
                hits.append(hit)
    return sorted(hits, key=lambda h: -h.score)[:limit]


def _checks_for(text: str) -> list[str]:
    t = text.lower()
    checks = ["ui"]
    if re.search(r"ceil|equals|number of|count|minutes|calculat", t):
        checks += ["calculation", "api", "data"]
    if re.search(r"design|field|button|control|select", t):
        checks.append("figma")
    if re.search(r"load|fast|slow|performance|seconds", t):
        checks.append("performance")
    return list(dict.fromkeys(checks))


def _ambiguity(text: str) -> tuple[bool, str]:
    m = VAGUE.search(text)
    if m and not re.search(r"\d", text):
        return True, f"'{m.group(0)}' has no measurable threshold"
    return False, ""


def heuristic_intent(story: Story, sources: list[str]) -> IntentModel:
    acs = []
    for ac in story.acceptance_criteria:
        ambiguous, reason = _ambiguity(ac.text)
        g = re.search(r"given (.*?), when (.*?), then (.*)", ac.text, re.IGNORECASE)
        acs.append(ACIntent(
            id=ac.id, text=ac.text,
            precondition=g.group(1) if g else "",
            action=g.group(2) if g else "",
            expected=g.group(3) if g else ac.text,
            checks=_checks_for(ac.text), ambiguous=ambiguous, ambiguity_reason=reason,
        ))
    return IntentModel(story_key=story.key, actor=story.actor, acs=acs, business_rules=story.business_rules,
                       ux_frames=story.figma_frames, context_sources=sources)


def build_intent(story: Story, ux: UXIntent, hits: list[Hit], llm: LLM) -> tuple[IntentModel, str]:
    sources = [h.chunk.source for h in hits]
    baseline = heuristic_intent(story, sources)
    try:
        intent = llm.structured(
            "build_intent", story.key,
            llm.prompt("build_intent_system"),
            llm.prompt("build_intent_user", story=story.model_dump_json(indent=2), story_key=story.key,
                       context=Retriever.format(hits),
                       ux=json.dumps({f: [c.model_dump(exclude_none=True) for c in cs] for f, cs in ux.frames.items()}, indent=1)),
            IntentModel,
        )
        method = "llm" if llm.is_live else "replay"
    except ReplayMissing:
        return baseline, "heuristic (no LLM key, no replay)"

    by_id = {a.id: a for a in intent.acs}
    merged = []
    for base in baseline.acs:
        ac = by_id.get(base.id, base)
        ac.text = base.text
        if base.ambiguous and not ac.ambiguous:
            ac.ambiguous, ac.ambiguity_reason = True, base.ambiguity_reason
        merged.append(ac)
    intent.acs = merged
    intent.story_key = story.key
    intent.context_sources = sources
    return intent, method
