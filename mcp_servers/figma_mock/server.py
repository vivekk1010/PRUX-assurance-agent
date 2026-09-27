"""Figma MCP server (mock by default).

FIGMA_SOURCE=fixture  -> reads fixtures/blog_notes.figma.json (default, offline)
FIGMA_SOURCE=rest     -> reads a real file via Figma REST API using FIGMA_TOKEN + FIGMA_FILE_KEY.
                         Story links, frame routes and approved variances still come from the fixture's x- keys.

Run standalone:  python -m mcp_servers.figma_mock.server
Inspect:         npx @modelcontextprotocol/inspector python -m mcp_servers.figma_mock.server
"""
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

from mcp_servers.figma_mock.figma_parser import parse_file
from mcp_servers.figma_mock.render_frames import FRAMES_DIR, frame_slug

FIXTURE = Path(__file__).parent / "fixtures" / "blog_notes.figma.json"
CACHE_DIR = Path(__file__).resolve().parents[2] / ".figma_cache"

mcp = FastMCP("figma-mock", log_level="WARNING")


@lru_cache(maxsize=1)
def _intent() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if os.getenv("FIGMA_SOURCE", "fixture") == "rest":
        resp = httpx.get(
            f"https://api.figma.com/v1/files/{os.environ['FIGMA_FILE_KEY']}",
            headers={"X-Figma-Token": os.environ["FIGMA_TOKEN"]},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        payload.setdefault("x-storyLinks", fixture.get("x-storyLinks", {}))
        payload.setdefault("x-approvedVariances", fixture.get("x-approvedVariances", []))
        payload.setdefault("x-frameRoutes", fixture.get("x-frameRoutes", {}))
        return parse_file(payload)
    return parse_file(fixture)


@mcp.tool()
def get_file_info() -> dict:
    """Name and version of the Figma file that holds the approved UX."""
    data = _intent()
    return {"file_name": data["file_name"], "version": data["version"], "frames": list(data["frames"])}


@mcp.tool()
def list_frames() -> list[dict]:
    """List design frames (screens) with node id and component count."""
    return [
        {"id": f["id"], "name": f["name"], "component_count": len(f["components"])}
        for f in _intent()["frames"].values()
    ]


@mcp.tool()
def get_frame_components(frame: str) -> list[dict]:
    """Components in a frame: kind (button, text-input, multi-select...), label, required, node_id."""
    frames = _intent()["frames"]
    if frame not in frames:
        raise ValueError(f"Unknown frame '{frame}'. Known: {list(frames)}")
    return frames[frame]["components"]


@mcp.tool()
def get_prototype_flows() -> list[dict]:
    """Prototype navigation: from_frame, trigger_label, to_frame."""
    return _intent()["flows"]


@mcp.tool()
def get_approved_variances() -> list[dict]:
    """Design differences product has approved (e.g. alternative button copy)."""
    return _intent()["approved_variances"]


@mcp.tool()
def get_story_frames(story_key: str) -> list[str]:
    """Frames linked to a Jira story key."""
    return _intent()["story_links"].get(story_key, [])


@mcp.tool()
def get_frame_routes() -> dict:
    """Application route for each frame (Dev Mode link): path and whether login is required."""
    return _intent()["frame_routes"]


@mcp.tool()
def get_frame_image(frame: str) -> dict:
    """Exported PNG of a frame. Returns a local file path, size and source (fixture or figma-rest)."""
    data = _intent()
    if frame not in data["frames"]:
        raise ValueError(f"Unknown frame '{frame}'. Known: {list(data['frames'])}")
    info = data["frames"][frame]
    if os.getenv("FIGMA_SOURCE", "fixture") == "rest":
        key = os.environ["FIGMA_FILE_KEY"]
        resp = httpx.get(f"https://api.figma.com/v1/images/{key}", params={"ids": info["id"], "format": "png", "scale": 1},
                         headers={"X-Figma-Token": os.environ["FIGMA_TOKEN"]}, timeout=60)
        resp.raise_for_status()
        url = resp.json()["images"][info["id"]]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{frame_slug(frame)}.png"
        path.write_bytes(httpx.get(url, timeout=60).content)
        source = "figma-rest"
    else:
        path = FRAMES_DIR / f"{frame_slug(frame)}.png"
        if not path.exists():
            subprocess.run([sys.executable, "-m", "mcp_servers.figma_mock.render_frames"], check=True, capture_output=True)
        source = "fixture"
    return {"frame": frame, "path": str(path), "width": info.get("width"), "height": info.get("height"), "source": source}


if __name__ == "__main__":
    mcp.run()
