"""Target application adapters."""
from agent.adapters.base import TargetAdapter
from agent.adapters.generic_web import GenericWebAdapter
from agent.adapters.stageui import StageUIAdapter


def get_adapter(settings) -> TargetAdapter:
    adapter = getattr(settings, "target_adapter", "stageui")
    if adapter == "stageui":
        return StageUIAdapter(settings)
    if adapter == "generic_web":
        return GenericWebAdapter(settings)
    raise ValueError(f"Unknown TARGET_ADAPTER '{adapter}'")


__all__ = ["TargetAdapter", "get_adapter"]
