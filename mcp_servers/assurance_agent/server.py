"""Expose the assurance agent as MCP tools so it can be driven from Cursor, Claude Desktop or any MCP client.

  python -m mcp_servers.assurance_agent.server
"""
import json
import subprocess
import sys

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


def _run_cli(*args: str) -> str | dict:
    proc = subprocess.run([sys.executable, "-m", "agent", *args, "--start-stage"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:] or proc.stdout[-2000:]}
    return (get_settings().runs_dir / "LATEST").read_text(encoding="utf-8").strip()


@mcp.tool()
def check_figma_conformance() -> dict:
    """Compare every Figma frame with the live Stage screen. Returns a verdict per frame with reasons and evidence."""
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
    """Run the full assurance loop for one story against Stage and return per-AC labels with rationale."""
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


if __name__ == "__main__":
    mcp.run()
