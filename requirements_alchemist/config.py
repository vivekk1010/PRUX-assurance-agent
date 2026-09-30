"""Configuration with secrets supplied only through environment variables."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    name: str = "Requirements Alchemist"
    host: str = "127.0.0.1"
    port: int = 5070
    debug: bool = False
    llm_provider: str = "openai-compatible"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key_env: str = "OPENAI_API_KEY"
    llm_timeout_seconds: float = 90.0
    llm_temperature: float = 0.1
    source_max_chars: int = 120_000
    source_max_download_bytes: int = 5_000_000
    retrieval_top_k: int = 6
    reference_dir: Path = ROOT / "requirements_alchemist" / "reference_data"
    workspace_dir: Path = ROOT / ".requirements-alchemist"
    output_dir: Path = ROOT / "generated_stories"
    allowed_source_hosts: tuple[str, ...] = ()
    figma_token_env: str = "FIGMA_ACCESS_TOKEN"
    atlassian_base_url: str = ""
    atlassian_email_env: str = "ATLASSIAN_EMAIL"
    atlassian_token_env: str = "ATLASSIAN_API_TOKEN"
    jira_project_key: str = ""
    jira_issue_type: str = "Story"
    jira_push_enabled: bool = False
    require_human_approval: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or Path(
            os.getenv(
                "REQUIREMENTS_ALCHEMIST_CONFIG",
                ROOT / "config" / "requirements-alchemist.json",
            )
        )
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        paths = {"reference_dir", "workspace_dir", "output_dir"}
        for key in paths & data.keys():
            candidate = Path(data[key])
            data[key] = candidate if candidate.is_absolute() else ROOT / candidate
        if "allowed_source_hosts" in data:
            data["allowed_source_hosts"] = tuple(data["allowed_source_hosts"])

        env_overrides = {
            "llm_provider": os.getenv("RA_LLM_PROVIDER"),
            "llm_model": os.getenv("RA_LLM_MODEL"),
            "llm_base_url": os.getenv("RA_LLM_BASE_URL"),
            "atlassian_base_url": os.getenv("ATLASSIAN_BASE_URL"),
            "jira_project_key": os.getenv("JIRA_PROJECT_KEY"),
        }
        data.update({key: value for key, value in env_overrides.items() if value})
        data["jira_push_enabled"] = _bool_env(
            "RA_JIRA_PUSH_ENABLED", bool(data.get("jira_push_enabled", False))
        )
        data["require_human_approval"] = _bool_env(
            "RA_REQUIRE_HUMAN_APPROVAL",
            bool(data.get("require_human_approval", True)),
        )
        return cls(**data)

    def secret_values(self) -> list[str]:
        names = (
            self.llm_api_key_env,
            self.figma_token_env,
            self.atlassian_email_env,
            self.atlassian_token_env,
        )
        return [os.environ[name] for name in names if os.getenv(name)]
