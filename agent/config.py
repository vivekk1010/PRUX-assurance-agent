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


def _env(primary: str, legacy: str, default: str = "") -> str:
    value = os.getenv(primary)
    return value if value else os.getenv(legacy, default)


@dataclass
class Settings:
    target_adapter: str = field(default_factory=lambda: os.getenv("TARGET_ADAPTER", "stageui"))
    target_profile: Path | None = field(default_factory=lambda: Path(os.environ["TARGET_PROFILE"]) if os.getenv("TARGET_PROFILE") else None)
    target_feature_map: Path | None = field(
        default_factory=lambda: Path(os.environ["TARGET_FEATURE_MAP"]) if os.getenv("TARGET_FEATURE_MAP") else None
    )
    stage_base_url: str = field(default_factory=lambda: _env("TARGET_BASE_URL", "STAGE_BASE_URL", "http://127.0.0.1:5055").rstrip("/"))
    stage_user: str = field(default_factory=lambda: _env("TARGET_USER", "STAGE_USER", "alice"))
    stage_password: str = field(default_factory=lambda: _env("TARGET_PASSWORD", "STAGE_PASSWORD", ""))
    target_auth_method: str = field(default_factory=lambda: os.getenv("TARGET_AUTH_METHOD", "form"))
    target_storage_state: Path | None = field(
        default_factory=lambda: Path(os.environ["TARGET_STORAGE_STATE"]) if os.getenv("TARGET_STORAGE_STATE") else None
    )
    target_headers_json: str = field(default_factory=lambda: os.getenv("TARGET_HEADERS_JSON", "{}"))
    target_health_path: str = field(default_factory=lambda: os.getenv("TARGET_HEALTH_PATH", "/login"))
    target_allowed_origins: list[str] = field(
        default_factory=lambda: [v.strip() for v in os.getenv("TARGET_ALLOWED_ORIGINS", "").split(",") if v.strip()]
    )
    target_read_only: bool = field(default_factory=lambda: _bool("TARGET_READ_ONLY", False))
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
    rag_mode: str = field(default_factory=lambda: os.getenv("RAG_MODE", "hybrid"))
    rag_min_score: float | None = field(
        default_factory=lambda: float(os.environ["RAG_MIN_SCORE"]) if os.getenv("RAG_MIN_SCORE") else None
    )
    rag_rrf_k: int = field(default_factory=lambda: int(os.getenv("RAG_RRF_K", "60")))

    max_recovery_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_RECOVERY_ATTEMPTS", "2")))
    headless: bool = field(default_factory=lambda: _bool("HEADLESS", True))
    step_timeout_ms: int = field(default_factory=lambda: int(os.getenv("STEP_TIMEOUT_MS", "5000")))
    performance_enabled: bool = field(default_factory=lambda: _bool("PERFORMANCE_ENABLED", False))
    performance_auto_run: bool = field(default_factory=lambda: _bool("PERFORMANCE_AUTO_RUN", False))
    performance_fail_on_regression: bool = field(
        default_factory=lambda: _bool("PERFORMANCE_FAIL_ON_REGRESSION", True)
    )
    performance_require_baseline: bool = field(
        default_factory=lambda: _bool("PERFORMANCE_REQUIRE_BASELINE", False)
    )
    performance_min_samples: int = field(
        default_factory=lambda: int(os.getenv("PERFORMANCE_MIN_SAMPLES", "3"))
    )
    performance_max_cv: float = field(
        default_factory=lambda: float(os.getenv("PERFORMANCE_MAX_CV", "0.35"))
    )
    advisory_evaluation_enabled: bool = field(
        default_factory=lambda: _bool("ADVISORY_EVALUATION_ENABLED", False)
    )

    stories_dir: Path = ROOT / "stories"
    knowledge_dir: Path = ROOT / "knowledge_base"
    rag_index_dir: Path = field(default_factory=lambda: ROOT / os.getenv("RAG_INDEX_DIR", ".rag_index"))
    runs_dir: Path = field(default_factory=lambda: ROOT / os.getenv("RUNS_DIR", "runs"))
    test_plans_dir: Path = field(default_factory=lambda: ROOT / os.getenv("TEST_PLANS_DIR", "test_plans"))
    performance_config: Path = field(
        default_factory=lambda: ROOT / os.getenv("PERFORMANCE_CONFIG", "config/performance.json")
    )
    performance_baselines_dir: Path = field(
        default_factory=lambda: ROOT / os.getenv("PERFORMANCE_BASELINES_DIR", "performance-baselines")
    )
    advisory_evaluation_config: Path = field(
        default_factory=lambda: ROOT / os.getenv(
            "ADVISORY_EVALUATION_CONFIG", "config/advisory-evaluation.json"
        )
    )
    replay_dir: Path = ROOT / "llm" / "replay"
    prompts_dir: Path = ROOT / "llm" / "prompts"


def get_settings() -> Settings:
    return Settings()
