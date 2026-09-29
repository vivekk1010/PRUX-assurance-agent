"""Run one scenario: guardrails -> deterministic step execution -> bounded LLM recovery (ReAct) on locator failure."""
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from agent.guardrails import check_step
from agent.adapters import get_adapter
from agent.models import Scenario, ScenarioResult, Step, StepResult, Target, UXIntent
from agent.tools.browser import BrowserSession
from agent.tool_registry import RegistryConfig, ToolRegistry
from llm import LLM

INTERACTIVE = {"goto", "fill", "click", "select"}

RECOVERY_TOOLS = [
    {"type": "function", "function": {
        "name": "click", "description": "Click a visible button or link.",
        "parameters": {"type": "object", "properties": {
            "role": {"type": "string", "enum": ["button", "link"]}, "name": {"type": "string"}},
            "required": ["role", "name"]}}},
    {"type": "function", "function": {
        "name": "fill", "description": "Fill the input with this visible label using the planned value.",
        "parameters": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}}},
    {"type": "function", "function": {
        "name": "select", "description": "Use the dropdown with this visible label with the planned values.",
        "parameters": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}}},
    {"type": "function", "function": {
        "name": "give_up", "description": "No visible element matches the intent.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]


@lru_cache(maxsize=1)
def recovery_registry() -> ToolRegistry:
    tools = []
    handlers = {}
    for item in RECOVERY_TOOLS:
        function = item["function"]
        name = function["name"]
        tools.append({
            "name": name, "description": function["description"],
            "input_schema": function["parameters"], "enabled": True,
            "surfaces": ["recovery"], "risk": "low", "timeout": 5,
            "capabilities": ["browser.recovery"] if name != "give_up" else [],
            "handler": {"type": "builtin", "name": name},
        })
        handlers[name] = lambda arguments: arguments
    return ToolRegistry(
        RegistryConfig.model_validate({"version": 1, "tools": tools}),
        builtin_handlers=handlers,
    )


def _recovery_step(choice: dict, planned: Step) -> Optional[Step]:
    name, args = choice.get("name"), choice.get("arguments", {})
    if name == "click":
        return Step(action="click", target=Target(role=args.get("role"), name=args.get("name")))
    if name == "fill":
        return Step(action="fill", target=Target(label=args.get("label")), value=planned.value)
    if name == "select":
        return Step(action="select", target=Target(label=args.get("label")), values=planned.values, value=planned.value)
    return None


def _recover(browser: BrowserSession, llm: LLM, settings, scenario: Scenario, step: Step,
             index: int, failed: StepResult) -> Optional[StepResult]:
    adapter = get_adapter(settings)
    registry = recovery_registry()
    available = registry.authorized_tools(
        surface="recovery", capabilities={"browser.recovery"}, max_risk="low"
    )
    for attempt in range(1, settings.max_recovery_attempts + 1):
        choice = llm.choose_tool(
            "recover_step", f"{scenario.id}-step{index:02d}-a{attempt}",
            llm.prompt("recover_step_system"),
            llm.prompt("recover_step_user", scenario_title=scenario.title, ac_ids=", ".join(scenario.ac_ids),
                       failed_step=failed.description, failure=failed.detail,
                       url=browser.page.url, snapshot=browser.snapshot()),
            [registry.llm_schema(tool) for tool in available],
        )
        new_step = _recovery_step(choice or {}, step)
        if new_step is None:
            return None
        refusal = check_step(
            new_step, settings.stage_base_url, adapter.allowed_origins, settings.target_read_only
        )
        if refusal:
            return StepResult(index=index, action=step.action, description=failed.description,
                              status="refused", detail=f"recovery refused: {refusal}")
        retry = browser.execute(new_step, index)
        if retry.status == "ok":
            retry.status = "recovered"
            retry.detail = f"planned [{step.target.describe()}] not found; agent used {browser.describe(new_step)}"
            return retry
    return None


def run_scenario(settings, ux: UXIntent, llm: LLM, scenario: Scenario, out_dir: Path) -> ScenarioResult:
    start = time.perf_counter()
    results: list[StepResult] = []
    adapter = get_adapter(settings)
    with BrowserSession(settings, ux, out_dir) as browser:
        blocked_by: Optional[str] = None
        for index, step in enumerate(scenario.steps, start=1):
            if blocked_by:
                results.append(StepResult(index=index, action=step.action, description=browser.describe(step),
                                          status="skipped", detail=f"blocked by step {blocked_by}"))
                continue
            refusal = check_step(
                step, settings.stage_base_url, adapter.allowed_origins, settings.target_read_only
            )
            if refusal:
                result = StepResult(index=index, action=step.action, description=browser.describe(step),
                                    status="refused", detail=f"guardrail: {refusal}")
            else:
                result = browser.execute(step, index)
                if (result.status == "missing" and result.data.get("reason") == "not_found"
                        and step.action in INTERACTIVE and step.target):
                    result = _recover(browser, llm, settings, scenario, step, index, result) or result
            results.append(result)
            if step.action in INTERACTIVE and result.status in {"missing", "refused", "error"}:
                blocked_by = str(index)
    return ScenarioResult(
        scenario_id=scenario.id, ac_ids=scenario.ac_ids, title=scenario.title, steps=results,
        trace_path=str(out_dir / "trace.zip") if (out_dir / "trace.zip").exists() else None,
        network_path=str(out_dir / "network.json") if (out_dir / "network.json").exists() else None,
        duration_ms=int((time.perf_counter() - start) * 1000),
    )
