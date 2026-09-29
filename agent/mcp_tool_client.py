"""Transport-neutral invocation for tools declared in the tool registry."""
import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from agent.tool_registry import MCPServer


def _unwrap(result):
    if result.isError:
        raise RuntimeError(" ".join(getattr(item, "text", "") for item in result.content))
    if result.structuredContent is not None:
        content = result.structuredContent
        return content.get("result") if set(content) == {"result"} else content
    texts = [item.text for item in result.content if getattr(item, "type", "") == "text"]
    parsed = []
    for text in texts:
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append(text)
    return parsed[0] if len(parsed) == 1 else parsed


async def _call(server: MCPServer, tool: str, arguments: dict):
    if server.transport == "stdio":
        env = {**os.environ, **server.env}
        params = StdioServerParameters(command=server.command or "", args=server.args, env=env)
        context = stdio_client(params)
    elif server.transport == "sse":
        context = sse_client(server.url or "", headers=server.headers)
    else:
        context = streamablehttp_client(server.url or "", headers=server.headers)
    async with context as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            return _unwrap(await session.call_tool(tool, arguments))


def invoke_mcp(server: MCPServer, tool: str, arguments: dict):
    return asyncio.run(_call(server, tool, arguments))
