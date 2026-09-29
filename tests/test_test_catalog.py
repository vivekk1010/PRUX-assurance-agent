from pathlib import Path

from agent.models import Step, TestCase as PlanCase, TestPlan as Plan
from agent.test_catalog import TestCatalog


def _plan(version=1):
    return Plan(
        id=f"B-1-v{version}-hash",
        version=version,
        story_key="B-1",
        source_hashes={},
        cases=[
            PlanCase(
                id="TC-1", story_key="B-1", ac_ids=["AC-1"], title="one",
                steps=[Step(action="goto", path="/")],
                feature_ids=["login"], figma_frames=["Login"],
            )
        ],
    )


def test_catalog_versions_and_approved_selection(tmp_path: Path):
    catalog = TestCatalog(tmp_path)
    plan = _plan()
    catalog.save(plan)
    assert catalog.next_version("B-1") == 2
    loaded = catalog.load("B-1")
    assert loaded.id == plan.id
    assert catalog.select([loaded], story="B-1") == []
    loaded.cases[0].status = "APPROVED"
    catalog.replace_reviewed(loaded)
    selected = catalog.select([catalog.load("B-1")], feature="login")
    assert [case.id for case in selected] == ["TC-1"]


def test_catalog_frame_filter(tmp_path: Path):
    plan = _plan()
    plan.cases[0].status = "APPROVED"
    catalog = TestCatalog(tmp_path)
    assert catalog.select([plan], frame="Other") == []
    assert catalog.select([plan], frame="Login")[0].id == "TC-1"
