import json
from types import SimpleNamespace

from agent.chat import ChatHarness, plain, summarize
from agent.config import get_settings


class ScriptedLLM:
    """Returns queued assistant messages instead of calling a model."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def prompt(self, name):
        return "system"

    def _chat(self, task, key, messages, **kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


def _tool_call(name, args, call_id="c1"):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=call_id, function=fn,
                           model_dump=lambda: {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}})


def _msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def test_chat_runs_tool_then_answers():
    llm = ScriptedLLM([_msg(tool_calls=[_tool_call("list_stories", {})]), _msg("There are 5 stories.")])
    harness = ChatHarness(get_settings(), llm, log=lambda m: None)
    assert harness.ask("what can you test?") == "There are 5 stories."
    tool_msg = llm.seen[1][-1]
    assert tool_msg["role"] == "tool" and "BLOG-103" in tool_msg["content"]


def test_unknown_story_is_rejected_without_running():
    harness = ChatHarness(get_settings(), ScriptedLLM([]), log=lambda m: None)
    out = json.loads(harness.call_tool("run_story_assurance", {"story_keys": ["BLOG-999"]}))
    assert "unknown stories" in out["error"]
    assert harness._stage_up is False


def test_tool_output_masks_stage_password():
    settings = get_settings()
    harness = ChatHarness(settings, ScriptedLLM([]), log=lambda m: None)
    harness._tool_show_story = lambda story_key: {"text": f"password is {settings.stage_password}"}
    assert settings.stage_password not in harness.call_tool("show_story", {"story_key": "BLOG-101"})


def test_plain_strips_markdown_for_terminal():
    text = "### Result\n- **My Blogs**: GAP  \n- [Trace](C:\\\\runs\\\\trace.zip)"
    assert plain(text) == "Result\n- My Blogs: GAP\n- Trace: C:\\runs\\trace.zip"


def test_summarize_gives_verdicts_and_absolute_evidence(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({
        "meta": {"run_id": "r1"},
        "figma_conformance": [{"frame": "My Blogs", "route": "/blogs", "label": "GAP", "rationale": "multi-select expected",
                               "components": [{"node_id": "2:6", "kind": "multi-select", "label": "Filter by tags",
                                               "status": "mismatch", "detail": "single-select observed"}],
                               "flows": [], "design_image": "figma/my-blogs/design.png", "live_image": "figma/my-blogs/live.png"}],
        "stories": [{"story_key": "BLOG-103", "title": "Metadata", "label": "DEFECT",
                     "ac_verdicts": [{"ac_id": "AC-03", "label": "DEFECT", "rationale": "UI=2 expected=3",
                                      "evidence": ["BLOG-103/SC-103-03/trace.zip"]}]}],
    }), encoding="utf-8")
    out = summarize(tmp_path)
    assert out["figma_frames"][0]["problems"] == ["2:6 multi-select 'Filter by tags': mismatch single-select observed"]
    assert out["stories"][0]["acceptance_criteria"][0]["evidence"][0].startswith(str(tmp_path))
