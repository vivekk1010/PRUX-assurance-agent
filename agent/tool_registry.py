"""Configurable, authorization-aware tool registry.

The registry deliberately does not create MCP clients.  MCP execution is
delegated to an injected callable so the core stays transport-independent and
can be tested without network access.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

ToolHandler = Callable[[dict[str, Any]], Any]
MCPHandler = Callable[["MCPServer", str, dict[str, Any]], Any]


class ToolRegistryError(RuntimeError):
    """Base error raised by the tool registry."""


class ToolNotFoundError(ToolRegistryError):
    pass


class ToolAuthorizationError(ToolRegistryError):
    pass


class ToolInputError(ToolRegistryError):
    pass


class ToolTimeoutError(ToolRegistryError):
    pass


class BuiltinHandler(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["builtin"]
    name: str = Field(min_length=1)


class PythonHandler(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["python"]
    import_path: str = Field(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")


class MCPHandlerDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["mcp"]
    server: str = Field(min_length=1)
    tool: str = Field(min_length=1)


class MCPServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "sse", "streamable-http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport_config(self) -> "MCPServer":
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio MCP servers require command")
            if self.url is not None:
                raise ValueError("stdio MCP servers cannot define url")
        else:
            if not self.url or not re.match(r"^https?://", self.url):
                raise ValueError(f"{self.transport} MCP servers require an http(s) url")
            if self.command is not None or self.args:
                raise ValueError(f"{self.transport} MCP servers cannot define command or args")
        return self


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    enabled: bool = True
    surfaces: set[str] = Field(min_length=1)
    risk: Literal["low", "medium", "high", "critical"] = "low"
    timeout: float = Field(default=10.0, gt=0, le=300)
    capabilities: set[str] = Field(default_factory=set)
    handler: BuiltinHandler | PythonHandler | MCPHandlerDescriptor = Field(discriminator="type")

    @model_validator(mode="after")
    def validate_schema(self) -> "ToolDefinition":
        _validate_schema_definition(self.input_schema)
        return self


class RegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    mcp_servers: dict[str, MCPServer] = Field(default_factory=dict)
    tools: list[ToolDefinition]

    @model_validator(mode="after")
    def validate_references(self) -> "RegistryConfig":
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        missing = {
            tool.handler.server
            for tool in self.tools
            if isinstance(tool.handler, MCPHandlerDescriptor)
            and tool.handler.server not in self.mcp_servers
        }
        if missing:
            raise ValueError(f"unknown MCP server(s): {', '.join(sorted(missing))}")
        return self


def _builtin_echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return arguments


def _builtin_health(_: dict[str, Any]) -> dict[str, str]:
    return {"status": "ok"}


DEFAULT_BUILTINS: dict[str, ToolHandler] = {
    "echo": _builtin_echo,
    "health": _builtin_health,
}

_RISK_LEVEL = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _validate_schema_definition(schema: Any, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{path}: schema must be an object")
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in _JSON_TYPES:
        raise ValueError(f"{path}: unsupported schema type {schema_type!r}")
    if "required" in schema and (
        not isinstance(schema["required"], list)
        or not all(isinstance(item, str) for item in schema["required"])
    ):
        raise ValueError(f"{path}.required must be a list of strings")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError(f"{path}.properties must be an object")
    for name, child in properties.items():
        _validate_schema_definition(child, f"{path}.properties.{name}")
    if "items" in schema:
        _validate_schema_definition(schema["items"], f"{path}.items")


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, _JSON_TYPES[expected])


def _validate_input(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if expected and not _matches_json_type(value, expected):
        raise ToolInputError(f"{path} must be {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolInputError(f"{path} must be one of {schema['enum']!r}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ToolInputError(f"{path} is missing required field(s): {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False:
            extra = value.keys() - properties.keys()
            if extra:
                raise ToolInputError(f"{path} has unexpected field(s): {', '.join(sorted(extra))}")
        for key, item in value.items():
            if key in properties:
                _validate_input(item, properties[key], f"{path}.{key}")
    elif isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_input(item, schema["items"], f"{path}[{index}]")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ToolInputError(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolInputError(f"{path} is longer than maxLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ToolInputError(f"{path} does not match the required pattern")


class ToolRegistry:
    def __init__(
        self,
        config: RegistryConfig,
        *,
        builtin_handlers: Mapping[str, ToolHandler] | None = None,
        mcp_handler: MCPHandler | None = None,
    ):
        self.config = config
        self._tools = {tool.name: tool for tool in config.tools}
        self._builtins = {**DEFAULT_BUILTINS, **(builtin_handlers or {})}
        self._mcp_handler = mcp_handler
        self._resolved_python: dict[str, ToolHandler] = {}

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        builtin_handlers: Mapping[str, ToolHandler] | None = None,
        mcp_handler: MCPHandler | None = None,
    ) -> "ToolRegistry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            RegistryConfig.model_validate(raw),
            builtin_handlers=builtin_handlers,
            mcp_handler=mcp_handler,
        )

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"unknown tool: {name}") from exc

    @staticmethod
    def llm_schema(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    def authorized_tools(
        self,
        *,
        surface: str,
        capabilities: set[str] | frozenset[str] = frozenset(),
        max_risk: Literal["low", "medium", "high", "critical"] = "low",
    ) -> list[ToolDefinition]:
        return [
            tool
            for tool in self.config.tools
            if self.is_authorized(
                tool, surface=surface, capabilities=capabilities, max_risk=max_risk
            )
        ]

    @staticmethod
    def is_authorized(
        tool: ToolDefinition,
        *,
        surface: str,
        capabilities: set[str] | frozenset[str],
        max_risk: Literal["low", "medium", "high", "critical"],
    ) -> bool:
        return (
            tool.enabled
            and surface in tool.surfaces
            and _RISK_LEVEL[tool.risk] <= _RISK_LEVEL[max_risk]
            and tool.capabilities.issubset(capabilities)
        )

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        surface: str,
        capabilities: set[str] | frozenset[str] = frozenset(),
        max_risk: Literal["low", "medium", "high", "critical"] = "low",
    ) -> Any:
        tool = self.get(name)
        if not self.is_authorized(
            tool, surface=surface, capabilities=capabilities, max_risk=max_risk
        ):
            raise ToolAuthorizationError(
                f"tool {name!r} is disabled or not authorized for this surface, risk, or capability set"
            )
        _validate_input(arguments, tool.input_schema)
        handler = self._resolve_handler(tool)
        return self._run_with_timeout(handler, arguments, tool.timeout, tool.name)

    def _resolve_handler(self, tool: ToolDefinition) -> ToolHandler:
        descriptor = tool.handler
        if isinstance(descriptor, BuiltinHandler):
            try:
                return self._builtins[descriptor.name]
            except KeyError as exc:
                raise ToolRegistryError(f"unknown built-in handler: {descriptor.name}") from exc

        if isinstance(descriptor, PythonHandler):
            if descriptor.import_path not in self._resolved_python:
                module_name, attribute = descriptor.import_path.split(":", 1)
                candidate = getattr(importlib.import_module(module_name), attribute)
                if not callable(candidate):
                    raise ToolRegistryError(f"Python handler is not callable: {descriptor.import_path}")
                self._resolved_python[descriptor.import_path] = candidate
            return self._resolved_python[descriptor.import_path]

        if self._mcp_handler is None:
            raise ToolRegistryError("MCP tool execution requires an injected mcp_handler")
        server = self.config.mcp_servers[descriptor.server]
        return lambda arguments: self._mcp_handler(server, descriptor.tool, arguments)

    @staticmethod
    def _run_with_timeout(
        handler: ToolHandler, arguments: dict[str, Any], timeout: float, name: str
    ) -> Any:
        def run() -> Any:
            result = handler(arguments)
            return asyncio.run(result) if inspect.isawaitable(result) else result

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
        future = executor.submit(run)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise ToolTimeoutError(f"tool {name!r} exceeded {timeout:g}s timeout") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
