import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlparse

from agent.models import Step


class TargetAdapter(Protocol):
    settings: object
    name: str

    def login_steps(self) -> list[Step]: ...
    def reset(self) -> None: ...
    def context_options(self) -> dict: ...
    def secrets(self) -> list[str]: ...
    def supports(self, capability: str) -> bool: ...
    @property
    def health_url(self) -> str: ...
    @property
    def start_module(self) -> str | None: ...
    @property
    def list_path(self) -> str: ...
    @property
    def row_title_testid(self) -> str: ...


class BaseAdapter:
    name = "base"

    def __init__(self, settings):
        self.settings = settings
        self.profile = self._load_profile(getattr(settings, "target_profile", None))

    @staticmethod
    def _load_profile(path: Path | None) -> dict:
        if path is None:
            return {}
        if not path.is_file():
            raise FileNotFoundError(f"TARGET_PROFILE does not exist: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def health_url(self) -> str:
        path = self.profile.get("health_path", self.settings.target_health_path)
        return urljoin(self.settings.stage_base_url + "/", path.lstrip("/"))

    @property
    def allowed_origins(self) -> list[str]:
        configured = self.settings.target_allowed_origins or self.profile.get("allowed_origins", [])
        if configured:
            return configured
        parsed = urlparse(self.settings.stage_base_url)
        return [f"{parsed.scheme}://{parsed.netloc}"]

    @property
    def start_module(self) -> str | None:
        return None

    @property
    def list_path(self) -> str:
        return self.profile.get("list_path", "/")

    @property
    def row_title_testid(self) -> str:
        return self.profile.get("row_title_testid", "row-title")

    def login_steps(self) -> list[Step]:
        return []

    def reset(self) -> None:
        return None

    def context_options(self) -> dict:
        return {}

    def secrets(self) -> list[str]:
        return [getattr(self.settings, "stage_password", "")]

    def supports(self, capability: str) -> bool:
        return capability in set(self.profile.get("capabilities", []))

    def check_calculation(self, session, name: str):
        return "error", f"target adapter '{self.name}' does not provide calculation probes", {}
