"""Story + UX intent + retrieved context -> structured expected-behavior record (IntentModel)."""
import json
import re

from agent.models import ACIntent, CitationRef, ConflictNote, IntentModel, Story, UXIntent
from llm import LLM, ReplayMissing
from rag.retriever import Retriever
from rag.store import Hit

VAGUE = re.compile(
    r"\b(fast|quick(ly)?|slow|user[- ]friendly|intuitive|nice|easy|good|responsive|appropriate|reasonable|smooth|clean)\b",
    re.IGNORECASE,
)


def retrieve_context(story: Story, retriever: Retriever, k_per_query: int = 3, limit: int = 10) -> list[Hit]:
    """Retrieve exact referenced rules plus focused context for each AC."""
    seen, hits = set(), []
    for hit in retriever.search_exact_rules(story.business_rules):
        if hit.chunk.id not in seen:
            seen.add(hit.chunk.id)
            hits.append(hit)
    queries = [(story.title, None)] + [(ac.text, ac.id) for ac in story.acceptance_criteria]
    for query, ac_id in queries:
        filters = {
            "doc_types": {
                "business_rule", "business_rule_group", "api_contract",
                "test_data", "glossary", "flow_test",
            }
        }
        for hit in retriever.search(
            f"{story.key} {ac_id or ''} {query}",
            k=k_per_query,
            filters=filters,
        ):
            if hit.chunk.id not in seen:
                seen.add(hit.chunk.id)
                hits.append(hit)
    return sorted(hits, key=lambda h: -h.score)[:limit]


def _grounding(story: Story, hits: list[Hit]) -> tuple[list[CitationRef], list[ConflictNote]]:
    citations = [
        CitationRef(
            id=f"C{i}", source=hit.chunk.source, chunk_id=hit.chunk.id,
            score=hit.score, excerpt=hit.chunk.text[:240],
        )
        for i, hit in enumerate(hits, 1)
    ]
    indexed_rules = {
        str(hit.chunk.meta.get("rule_id", "")).upper()
        for hit in hits if hit.chunk.meta.get("rule_id")
    }
    conflicts = [
        ConflictNote(
            kind="missing_rule", severity="error",
            detail=f"{rule_id} is referenced by {story.key} but was not retrieved.",
        )
        for rule_id in story.business_rules if rule_id.upper() not in indexed_rules
    ]
    combined_story = " ".join(ac.text for ac in story.acceptance_criteria).lower()
    for hit in hits:
        rule = hit.chunk.text.lower()
        if ("ceil" in combined_story and "floor" in rule) or ("floor" in combined_story and "ceil" in rule):
            conflicts.append(ConflictNote(
                kind="rule_vs_story", severity="warning",
                detail=f"Potential rounding conflict between {story.key} and {hit.chunk.source}.",
            ))
    return citations, conflicts


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
    citations, conflicts = _grounding(story, hits)
    baseline = heuristic_intent(story, sources)
    baseline.context_citations = citations
    baseline.conflicts = conflicts
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
    intent.context_citations = citations
    intent.conflicts = conflicts
    return intent, method
