import json
import os

from agent.config import get_settings
from agent.intent_builder import heuristic_intent
from agent.models import ScenarioPlan
from agent.sources.jira import list_story_keys, load_story
from rag.ingest import build_index, chunk_markdown
from rag.retriever import Retriever


def test_markdown_chunks_by_heading():
    s = get_settings()
    ids = [c.id for c in chunk_markdown(s.knowledge_dir / "business_rules.md")]
    assert "business_rules#br-meta-02-reading-time" in ids


def test_offline_rag_retrieves_business_rule(tmp_path):
    s = get_settings()
    build_index(s.stories_dir, s.knowledge_dir, tmp_path, None, "hashing", "")
    hits = Retriever(tmp_path).search("how is reading time calculated", k=3, source_prefix="knowledge_base")
    assert any("br-meta-02" in h.chunk.source for h in hits)


def test_heuristic_intent_flags_unmeasurable_ac():
    s = get_settings()
    intent = heuristic_intent(load_story(s.stories_dir, "BLOG-105"), [])
    flags = {a.id: a.ambiguous for a in intent.acs}
    assert flags == {"AC-01": False, "AC-02": False, "AC-03": True}


def test_replay_scenarios_cover_every_ac():
    s = get_settings()
    for key in list_story_keys(s.stories_dir):
        story = load_story(s.stories_dir, key)
        plan = ScenarioPlan.model_validate(
            json.loads((s.replay_dir / "generate_scenarios" / f"{key}.json").read_text(encoding="utf-8")))
        cited = {ac for sc in plan.scenarios for ac in sc.ac_ids}
        assert cited == {ac.id for ac in story.acceptance_criteria}, key
        for sc in plan.scenarios:
            for step in sc.steps:
                assert os.environ["STAGE_PASSWORD"] not in (step.value or ""), "replay fixtures must use ${STAGE_PASSWORD}"
