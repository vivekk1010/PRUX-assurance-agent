import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.tool_registry import (
    RegistryConfig,
    ToolAuthorizationError,
    ToolInputError,
    ToolRegistry,
    ToolTimeoutError,
)

ROOT = Path(__file__).resolve().parents[1]


def tool_config(handler, **overrides):
    tool = {
        "name": "example",
        "description": "Example tool",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "enabled": True,
        "surfaces": ["test"],
        "risk": "low",
        "timeout": 1,
        "capabilities": [],
        "handler": handler,
    }
    tool.update(overrides)
    return {"version": 1, "tools": [tool]}


def registry_for(handler, function=None, **overrides):
    config = RegistryConfig.model_validate(tool_config(handler, **overrides))
    builtins = {"test": function} if function else {}
    return ToolRegistry(config, builtin_handlers=builtins)


def test_repository_config_loads_and_builtin_and_python_handlers_run():
    registry = ToolRegistry.from_file(ROOT / "config" / "tools.json")

    assert registry.invoke("echo", {"message": "hello"}, surface="test") == {
        "message": "hello"
    }
    assert registry.invoke(
        "normalize_text",
        {"text": "  safe   sample  "},
        surface="test",
        capabilities={"text.normalize"},
    ) == {"text": "safe sample"}


@pytest.mark.parametrize(
    ("overrides", "invoke_kwargs"),
    [
        ({"enabled": False}, {"surface": "test"}),
        ({"surfaces": ["chat"]}, {"surface": "test"}),
        ({"risk": "high"}, {"surface": "test", "max_risk": "medium"}),
        (
            {"capabilities": ["files.read"]},
            {"surface": "test", "capabilities": set()},
        ),
    ],
)
def test_authorization_denies_disabled_surface_risk_and_capability(overrides, invoke_kwargs):
    registry = registry_for(
        {"type": "builtin", "name": "test"},
        lambda arguments: arguments,
        **overrides,
    )

    with pytest.raises(ToolAuthorizationError):
        registry.invoke("example", {"value": "ok"}, **invoke_kwargs)


def test_authorized_tools_filters_without_loading_handlers():
    registry = registry_for(
        {"type": "python", "import_path": "package_that_does_not_exist:handler"},
        capabilities=["files.read"],
        risk="medium",
    )

    assert registry.authorized_tools(surface="test") == []
    assert [tool.name for tool in registry.authorized_tools(
        surface="test", capabilities={"files.read"}, max_risk="medium"
    )] == ["example"]


def test_input_schema_is_enforced_before_handler_execution():
    called = False

    def handler(arguments):
        nonlocal called
        called = True
        return arguments

    registry = registry_for({"type": "builtin", "name": "test"}, handler)

    with pytest.raises(ToolInputError, match="missing required"):
        registry.invoke("example", {}, surface="test")
    with pytest.raises(ToolInputError, match="unexpected"):
        registry.invoke("example", {"value": "ok", "extra": True}, surface="test")
    with pytest.raises(ToolInputError, match="must be string"):
        registry.invoke("example", {"value": 3}, surface="test")
    assert called is False


def test_invalid_registry_and_mcp_references_are_rejected():
    malformed_schema = tool_config(
        {"type": "builtin", "name": "echo"},
        input_schema={"type": "made-up"},
    )
    with pytest.raises(ValidationError, match="unsupported schema type"):
        RegistryConfig.model_validate(malformed_schema)

    missing_server = tool_config(
        {"type": "mcp", "server": "missing", "tool": "lookup"}
    )
    with pytest.raises(ValidationError, match="unknown MCP server"):
        RegistryConfig.model_validate(missing_server)


def test_mcp_descriptor_uses_injected_executor_without_network():
    raw = tool_config({"type": "mcp", "server": "local", "tool": "lookup"})
    raw["mcp_servers"] = {
        "local": {"transport": "stdio", "command": "not-executed", "args": ["--safe"]}
    }
    calls = []

    def fake_mcp(server, tool, arguments):
        calls.append((server.command, tool, arguments))
        return {"result": "stubbed"}

    registry = ToolRegistry(RegistryConfig.model_validate(raw), mcp_handler=fake_mcp)

    assert registry.invoke("example", {"value": "query"}, surface="test") == {
        "result": "stubbed"
    }
    assert calls == [("not-executed", "lookup", {"value": "query"})]


def test_timeout_is_enforced():
    def slow_handler(arguments):
        time.sleep(0.1)
        return arguments

    registry = registry_for(
        {"type": "builtin", "name": "test"},
        slow_handler,
        timeout=0.01,
    )

    with pytest.raises(ToolTimeoutError, match="exceeded"):
        registry.invoke("example", {"value": "ok"}, surface="test")
