"""Typed runtime settings loaded from environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_REQUIRED = (
    "LLM_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_IDS",
    "GITHUB_TOKEN",
    "E2B_API_KEY",
)


class SettingsError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


def _parse_user_ids(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated list of Telegram user IDs into ints."""
    try:
        return tuple(int(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError as exc:
        raise SettingsError(f"TELEGRAM_ALLOWED_USER_IDS malformed: {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Immutable bundle of validated environment configuration."""

    llm_api_key: str
    telegram_bot_token: str
    telegram_allowed_user_ids: tuple[int, ...]
    github_token: str
    github_default_branch: str
    e2b_api_key: str
    log_level: str
    checkpoint_dir: Path
    chroma_dir: Path
    max_test_retries: int
    llm_provider: str = "huggingface"
    llm_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    llm_fallback_models: tuple[str, ...] = ()
    llm_base_url: str = "https://router.huggingface.co/v1"
    groq_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "clawcode"
    components: tuple[str, ...] = field(
        default=("llm", "telegram", "github", "e2b"),
        repr=False,
    )

    def verify(self) -> str:
        """Return a human-readable OK summary; raises if anything is missing."""
        return "OK: " + ", ".join(self.components)


def load() -> Settings:
    """Read env vars, validate, and return a Settings instance."""
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        raise SettingsError(f"Missing required env vars: {', '.join(missing)}")

    return Settings(
        llm_api_key=os.environ["LLM_API_KEY"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_allowed_user_ids=_parse_user_ids(os.environ["TELEGRAM_ALLOWED_USER_IDS"]),
        github_token=os.environ["GITHUB_TOKEN"],
        github_default_branch=os.getenv("GITHUB_DEFAULT_BRANCH", "main"),
        e2b_api_key=os.environ["E2B_API_KEY"],
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        checkpoint_dir=Path(os.getenv("CHECKPOINT_DIR", "./checkpoints")),
        chroma_dir=Path(os.getenv("CHROMA_DIR", "./chroma_data")),
        langsmith_tracing=os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
        langsmith_api_key=os.getenv("LANGCHAIN_API_KEY", ""),
        langsmith_project=os.getenv("LANGCHAIN_PROJECT", "clawcode"),
        max_test_retries=int(os.getenv("MAX_TEST_RETRIES", "3")),
        llm_provider=os.getenv("LLM_PROVIDER", "huggingface").strip().lower(),
        llm_model=os.getenv("LLM_MODEL", "Qwen/Qwen3-Coder-30B-A3B-Instruct"),
        llm_fallback_models=tuple(
            m.strip()
            for m in os.getenv(
                "LLM_FALLBACK_MODELS",
                "deepseek-ai/DeepSeek-R1-0528,meta-llama/Llama-3.3-70B-Instruct",
            ).split(",")
            if m.strip()
        ),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://router.huggingface.co/v1"),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
    )


settings = None  # populated lazily by get()


def get() -> Settings:
    """Module-level singleton accessor."""
    global settings
    if settings is None:
        settings = load()
    return settings
