import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _default_provider() -> str:
    if os.getenv("AZURE_OPENAI_API_KEY"):
        return "azure"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "replay"


@dataclass
class Settings:
    stage_base_url: str = field(default_factory=lambda: os.getenv("STAGE_BASE_URL", "http://127.0.0.1:5055").rstrip("/"))
    stage_user: str = field(default_factory=lambda: os.getenv("STAGE_USER", "alice"))
    stage_password: str = field(default_factory=lambda: os.getenv("STAGE_PASSWORD", ""))
    stage_db_path: Path = field(default_factory=lambda: ROOT / os.getenv("STAGE_DB_PATH", "stageui_app/instance/blog.db"))
    stage_reset_module: str = field(default_factory=lambda: os.getenv("STAGE_RESET_MODULE", "stageui_app.seed"))

    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", _default_provider()))
    llm_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    vision_model: str = field(default_factory=lambda: os.getenv("VISION_MODEL", "gpt-4o"))
    llm_record: bool = field(default_factory=lambda: _bool("LLM_RECORD", False))
    embedding_provider: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "openai" if os.getenv("OPENAI_API_KEY") else "hashing")
    )
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))

    max_recovery_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_RECOVERY_ATTEMPTS", "2")))
    headless: bool = field(default_factory=lambda: _bool("HEADLESS", True))
    step_timeout_ms: int = field(default_factory=lambda: int(os.getenv("STEP_TIMEOUT_MS", "5000")))

    stories_dir: Path = ROOT / "stories"
    knowledge_dir: Path = ROOT / "knowledge_base"
    rag_index_dir: Path = field(default_factory=lambda: ROOT / os.getenv("RAG_INDEX_DIR", ".rag_index"))
    runs_dir: Path = field(default_factory=lambda: ROOT / os.getenv("RUNS_DIR", "runs"))
    replay_dir: Path = ROOT / "llm" / "replay"
    prompts_dir: Path = ROOT / "llm" / "prompts"


def get_settings() -> Settings:
    return Settings()
