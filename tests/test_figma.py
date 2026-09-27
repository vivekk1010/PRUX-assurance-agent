import json

from agent.sources.figma_client import fetch_ux_intent
from mcp_servers.figma_mock.figma_parser import parse_file
from mcp_servers.figma_mock.server import FIXTURE


def test_parser_extracts_frames_components_and_flows():
    ux = parse_file(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert set(ux["frames"]) == {"Login", "My Blogs", "New Post"}
    kinds = {c["label"]: c["kind"] for c in ux["frames"]["My Blogs"]["components"]}
    assert kinds["Filter by tags"] == "multi-select"
    table = next(c for c in ux["frames"]["My Blogs"]["components"] if c["kind"] == "table")
    assert table["columns"] == ["Title", "Author", "Date", "Words", "Reading time"]
    assert {"from_frame": "Login", "trigger": "ON_CLICK", "trigger_label": "Log in", "to_frame": "My Blogs"} in ux["flows"]


def test_conditional_components_are_not_required():
    ux = parse_file(json.loads(FIXTURE.read_text(encoding="utf-8")))
    error = next(c for c in ux["frames"]["Login"]["components"] if c["kind"] == "error-text")
    assert error["required"] is False


def test_mcp_round_trip_scopes_to_story_frames():
    ux = fetch_ux_intent("BLOG-101")
    assert list(ux.frames) == ["Login"]
    assert ux.approved_variances == []
    assert fetch_ux_intent("BLOG-102").approved_variances
