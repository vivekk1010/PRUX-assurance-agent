import json
from pathlib import Path
from types import SimpleNamespace

from agent.conformance import _verdict, _visual_review
from agent.models import FlowCheck, Target, UXIntent, VisualObservation, VisualReview
from agent.sources.figma_client import fetch_ux_intent, list_tools
from agent.tools.browser import BrowserSession
from mcp_servers.figma_mock.figma_parser import parse_file
from mcp_servers.figma_mock.server import FIXTURE


def _finding(label, status, kind="button", detail=""):
    return {"node_id": "1:1", "kind": kind, "label": label, "status": status, "detail": detail}


def test_parser_returns_relative_boxes_and_routes():
    ux = parse_file(json.loads(FIXTURE.read_text(encoding="utf-8")))
    login = ux["frames"]["Login"]
    assert (login["width"], login["height"]) == (1280, 800)
    for c in login["components"]:
        b = c["box"]
        assert 0 <= b["x"] and b["x"] + b["width"] <= login["width"]
        assert 0 <= b["y"] and b["y"] + b["height"] <= login["height"]
    assert ux["frame_routes"]["Login"]["requires_login"] is False
    assert ux["frame_routes"]["New Post"]["path"] == "/blogs/new"


def test_mcp_exposes_frame_images_and_routes():
    assert {"get_frame_image", "get_frame_routes"} <= set(list_tools())
    ux = fetch_ux_intent(with_images=True)
    assert ux.frame_routes["My Blogs"]["path"] == "/blogs"
    assert all(Path(img["path"]).is_file() for img in ux.frame_images.values())


def test_verdict_precedence_and_pass_text():
    ok_flow = FlowCheck(trigger_label="Log in", to_frame="My Blogs", expected_path="/blogs", status="ok")
    label, text = _verdict("New Post", [_finding("Publish", "approved_variance", detail="rendered as 'Save post'")], [ok_flow], True)
    assert label == "PASS" and "Approved variances" in text

    label, _ = _verdict("My Blogs", [_finding("Filter by tags", "mismatch", "multi-select")], [ok_flow], True)
    assert label == "GAP"

    bad_flow = ok_flow.model_copy(update={"status": "mismatch", "detail": "landed on /login"})
    label, text = _verdict("My Blogs", [_finding("Filter by tags", "mismatch")], [bad_flow], True)
    assert label == "DEFECT" and "(also GAP)" in text

    label, _ = _verdict("Login", [], [], False)
    assert label == "RISK"


def test_visual_review_drops_conditional_and_approved_notes(tmp_path):
    review = VisualReview(summary="2 differences", observations=[
        VisualObservation(area="button", difference="Label reads 'Save post' instead of 'Publish'", severity="high"),
        VisualObservation(area="form", difference="'Invalid username or password' text not shown", severity="high"),
    ])
    llm = SimpleNamespace(prompt=lambda name: "", vision=lambda *a, **k: review)
    findings = [_finding("Publish", "approved_variance"), _finding("Invalid username or password", "skipped", "error-text")]
    variances = [{"frame": "New Post", "label": "Publish", "allowed_labels": ["Save post"], "reason": "copy change"}]
    out = _visual_review(llm, "New Post", tmp_path / "d.png", tmp_path / "l.png", findings, variances, print)
    assert out.observations == []
    assert "approved variances" in out.summary


def test_locator_candidates_include_equivalent_forms_and_variances():
    ux = UXIntent(approved_variances=[{"frame": "New Post", "label": "Publish", "allowed_labels": ["Save post"], "reason": "copy"}])
    session = BrowserSession(SimpleNamespace(stage_password="x"), ux, Path("."))
    cands = session._candidates(Target(label="Publish"))
    assert cands[0] == (Target(label="Publish"), "")
    targets = [c for c, _ in cands]
    assert Target(role="button", name="Publish") in targets
    assert Target(role="button", name="Save post") in targets
    assert any("approved variance" in note for _, note in cands)
    assert session._candidates(Target(testid="post-title")) == [(Target(testid="post-title"), "")]
