"""MCP client for the Figma server. Spawns the server over stdio and calls its tools."""
import asyncio
import json
import os
import sys
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import ROOT
from agent.models import UIComponent, UXFeature, UXIntent


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_servers.figma_mock.server"], env=env, cwd=str(ROOT)
    )


def _unwrap(result) -> Any:
    if result.isError:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in result.content))
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc["result"] if set(sc) == {"result"} else sc
    texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
    parsed = [json.loads(t) for t in texts]
    return parsed[0] if len(parsed) == 1 else parsed


async def _fetch(story_key: Optional[str], with_images: bool = False) -> tuple[UXIntent, list[str]]:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool: str, **args):
                return _unwrap(await session.call_tool(tool, args))

            info = await call("get_file_info")
            frames = await call("get_story_frames", story_key=story_key) if story_key else info["frames"]
            components = {f: [UIComponent(**c) for c in await call("get_frame_components", frame=f)] for f in frames}
            flows = await call("get_prototype_flows")
            variances = await call("get_approved_variances")
            routes = await call("get_frame_routes")
            features = await call("get_features")
            nodes = {f["name"]: f["id"] for f in await call("list_frames")}
            images = {f: await call("get_frame_image", frame=f) for f in frames} if with_images else {}
            tools = [t.name for t in (await session.list_tools()).tools]
    ux = UXIntent(
        file_name=info["file_name"], version=info["version"], frames=components,
        flows=[fl for fl in flows if fl["from_frame"] in frames],
        approved_variances=[v for v in variances if v.get("frame") in frames],
        frame_nodes={f: n for f, n in nodes.items() if f in frames},
        frame_routes={f: r for f, r in routes.items() if f in frames},
        frame_images=images,
        features=[
            UXFeature(**feature) for feature in features
            if not story_key or not feature.get("story_keys") or story_key in feature.get("story_keys", [])
        ],
    )
    return ux, tools


def fetch_ux_intent(story_key: Optional[str] = None, with_images: bool = False) -> UXIntent:
    """UX intent for one story's frames, or for the whole file when story_key is None."""
    return asyncio.run(_fetch(story_key, with_images))[0]


def list_tools() -> list[str]:
    return asyncio.run(_fetch(None))[1]
