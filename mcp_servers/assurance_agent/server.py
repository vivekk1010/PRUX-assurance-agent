"""Expose the assurance agent as MCP tools so it can be driven from Cursor, Claude Desktop or any MCP client.

  python -m mcp_servers.assurance_agent.server
"""
import json
import subprocess
import sys
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent.config import ROOT, get_settings
from agent.sources.jira import list_story_keys, load_story

mcp = FastMCP("PR-UX-assurance-agent", log_level="WARNING")


@mcp.tool()
def list_stories() -> list[dict]:
    """Jira stories available for assurance, with their acceptance criteria ids."""
    s = get_settings()
    return [
        {"key": k, "title": (st := load_story(s.stories_dir, k)).title, "acs": [a.id for a in st.acceptance_criteria]}
        for k in list_story_keys(s.stories_dir)
    ]


def _run_cli(*args: str, start_stage: bool = True) -> str | dict:
    command = [sys.executable, "-m", "agent", *args]
    if start_stage:
        command.append("--start-stage")
    proc = subprocess.run(command,
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:] or proc.stdout[-2000:]}
    latest = get_settings().runs_dir / "LATEST"
    return latest.read_text(encoding="utf-8").strip() if latest.exists() else ""


@mcp.tool()
def check_figma_conformance() -> dict:
    """Compare every Figma frame with the live StageUI screen. Returns a verdict per frame with reasons and evidence."""
    s = get_settings()
    run_id = _run_cli("conformance")
    if isinstance(run_id, dict):
        return run_id
    data = json.loads((s.runs_dir / run_id / "results.json").read_text(encoding="utf-8"))
    return {
        "frames": [
            {"frame": f["frame"], "route": f["route"], "label": f["label"], "rationale": f["rationale"],
             "visual_notes": [o["difference"] for o in (f.get("visual_review") or {}).get("observations", [])]}
            for f in data["figma_conformance"]
        ],
        "report": str(s.runs_dir / run_id / "report.html"),
    }


@mcp.tool()
def run_assurance(story_key: str) -> dict:
    """Run the full assurance loop for one story against StageUI and return per-AC labels with rationale."""
    s = get_settings()
    run_id = _run_cli("run", "--story", story_key, "--no-figma")
    if isinstance(run_id, dict):
        return run_id
    result = json.loads((s.runs_dir / run_id / story_key / "result.json").read_text(encoding="utf-8"))
    return {
        "story": story_key,
        "label": result["label"],
        "acs": [{"ac": v["ac_id"], "label": v["label"], "rationale": v["rationale"]} for v in result["ac_verdicts"]],
        "recommendation": result["recommendation"],
        "report": str(s.runs_dir / run_id / "report.html"),
    }


@mcp.tool()
def generate_test_cases(story_key: str, excel: bool = True) -> dict:
    """Generate a versioned draft plan without executing a browser."""
    args = ["generate", "--story", story_key]
    if excel:
        args.append("--excel")
    result = _run_cli(*args, start_stage=False)
    if isinstance(result, dict):
        return result
    s = get_settings()
    latest = s.test_plans_dir / story_key.upper() / "LATEST"
    if not latest.exists():
        return {"error": "plan generation did not create a catalog entry"}
    version = latest.read_text(encoding="utf-8").strip()
    return {
        "story": story_key.upper(), "version": int(version),
        "plan": str(s.test_plans_dir / story_key.upper() / f"v{version}.json"),
        "workbook": str(s.test_plans_dir / story_key.upper() / f"v{version}.xlsx") if excel else None,
    }


@mcp.tool()
def import_human_review(story_key: str, workbook: str, version: int | None = None) -> dict:
    """Validate and import approval fields and edited steps from an .xlsx workbook."""
    args = ["review", "import", "--story", story_key, "--file", workbook]
    if version is not None:
        args += ["--version", str(version)]
    result = _run_cli(*args, start_stage=False)
    return result if isinstance(result, dict) else {"story": story_key.upper(), "imported": True}


@mcp.tool()
def run_approved_tests(story: str | None = None, frame: str | None = None, feature: str | None = None) -> dict:
    """Execute approved test cases selected by exactly one story, Figma frame, or feature."""
    selected = [("--story", story), ("--frame", frame), ("--feature", feature)]
    selected = [(flag, value) for flag, value in selected if value]
    if len(selected) != 1:
        return {"error": "provide exactly one of story, frame, or feature"}
    run_id = _run_cli("run-approved", selected[0][0], selected[0][1])
    if isinstance(run_id, dict):
        return run_id
    return {"run_id": run_id, "report": str(get_settings().runs_dir / run_id / "report.html")}


@mcp.tool()
def list_performance_profiles() -> list[dict]:
    """List configured page, feature, component, API, and load performance profiles."""
    from agent.performance.profiles import PerformanceProfileRegistry

    settings = get_settings()
    registry = PerformanceProfileRegistry.from_file(settings.performance_config)
    return [
        {
            "id": profile.id,
            "scope": profile.scope,
            "enabled": profile.enabled,
            "selector": profile.selector.model_dump(exclude_none=True),
            "integrations": profile.integrations.model_dump(),
        }
        for profile in registry.config.profiles
    ]


@mcp.tool()
def run_performance_profile(profile_id: str) -> dict:
    """Run one explicitly configured performance profile and return its deterministic summary."""
    run_id = _run_cli("performance", "run", "--profile", profile_id)
    if isinstance(run_id, dict):
        return run_id
    path = get_settings().runs_dir / run_id / "performance.json"
    if not path.exists():
        return {"error": "performance run did not create performance.json"}
    return json.loads(path.read_text(encoding="utf-8"))


@mcp.tool()
def get_performance_results(run_id: str | None = None) -> dict:
    """Read performance results for a run, defaulting to the latest run."""
    settings = get_settings()
    if run_id is None:
        latest = settings.runs_dir / "LATEST"
        if not latest.exists():
            return {"error": "no run exists"}
        run_id = latest.read_text(encoding="utf-8").strip()
    root = (settings.runs_dir / run_id).resolve()
    if root.parent != settings.runs_dir.resolve():
        return {"error": "invalid run id"}
    path = root / "performance.json"
    if not path.exists():
        return {"error": f"run {run_id} has no performance results"}
    return json.loads(path.read_text(encoding="utf-8"))


def _configured_registry():
    from agent.mcp_tool_client import invoke_mcp
    from agent.tool_registry import ToolRegistry

    path = Path(os.getenv("AGENT_TOOLS_CONFIG", ROOT / "config" / "tools.json"))
    return ToolRegistry.from_file(path, mcp_handler=invoke_mcp)


@mcp.tool()
def list_configured_tools() -> list[dict]:
    """List enabled low-risk tools explicitly exposed to the MCP surface."""
    capabilities = {v.strip() for v in os.getenv("AGENT_TOOL_CAPABILITIES", "").split(",") if v.strip()}
    return [
        {"name": tool.name, "description": tool.description, "schema": tool.input_schema}
        for tool in _configured_registry().authorized_tools(
            surface="mcp", capabilities=capabilities, max_risk="low"
        )
    ]


@mcp.tool()
def invoke_configured_tool(name: str, arguments: dict) -> object:
    """Invoke one configured MCP-surface tool after schema and risk authorization."""
    capabilities = {v.strip() for v in os.getenv("AGENT_TOOL_CAPABILITIES", "").split(",") if v.strip()}
    return _configured_registry().invoke(
        name, arguments, surface="mcp", capabilities=capabilities, max_risk="low"
    )


if __name__ == "__main__":
    mcp.run()
