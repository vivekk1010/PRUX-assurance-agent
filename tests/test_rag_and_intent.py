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


def test_generated_plan_is_normalized(tmp_path):
    from types import SimpleNamespace

    from agent.models import Scenario, Step, Target
    from agent.scenario_generator import generate_scenarios
    from agent.sources.figma_client import fetch_ux_intent

    s = get_settings()
    intent = heuristic_intent(load_story(s.stories_dir, "BLOG-102"), [])
    plan = ScenarioPlan(scenarios=[Scenario(
        id="SC-102-04", story_key="BLOG-102", ac_ids=["AC-03", "AC-04"], title="t", rationale="r",
        steps=[Step(action="check_calculation", name="reading_time"),
               Step(action="expect_text", target=Target(label="error-text"), text="Title is required")])])
    llm = SimpleNamespace(prompt=lambda *a, **k: "", structured=lambda *a, **k: plan)
    retriever = SimpleNamespace(search=lambda *a, **k: [])
    out, notes = generate_scenarios(intent, fetch_ux_intent("BLOG-102"), retriever, llm)
    steps = out.scenarios[0].steps
    assert [st.action for st in steps] == ["expect_text"]
    assert steps[0].target == Target(text="Title is required")
    assert len(notes) == 2


def test_hard_coded_numbers_are_replaced_by_calculation_check():
    from types import SimpleNamespace

    from agent.models import Scenario, Step, Target
    from agent.scenario_generator import generate_scenarios
    from agent.sources.figma_client import fetch_ux_intent

    s = get_settings()
    intent = heuristic_intent(load_story(s.stories_dir, "BLOG-103"), [])
    plan = ScenarioPlan(scenarios=[Scenario(
        id="SC-103-02", story_key="BLOG-103", ac_ids=["AC-02"], title="t", rationale="r",
        steps=[Step(action="goto", path="/blogs"),
               Step(action="expect_text", target=Target(testid="post-words"), text="450")])])
    llm = SimpleNamespace(prompt=lambda *a, **k: "", structured=lambda *a, **k: plan)
    out, _ = generate_scenarios(intent, fetch_ux_intent("BLOG-103"), SimpleNamespace(search=lambda *a, **k: []), llm)
    assert [(st.action, st.name) for st in out.scenarios[0].steps] == [("goto", None), ("check_calculation", "word_count")]
