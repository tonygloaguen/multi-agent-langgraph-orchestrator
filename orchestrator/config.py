from __future__ import annotations

import asyncio as _asyncio
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    claude_model: str = "claude-opus-4-6"
    codex_model: str = "codex-mini-latest"
    gemini_model: str = "gemini-2.0-flash"
    orchestrator_max_repair_loops: int = Field(default=2, ge=1, le=5)
    orchestrator_task_timeout: int = Field(default=300, ge=30)
    orchestrator_context_max_tokens: int = Field(default=8000, ge=1000)
    gemini_fallback_enabled: bool = True
    rtk_enabled: bool = True
    handoffs_dir: Path = Path("./orchestrator/handoffs")
    state_dir: Path = Path("./orchestrator/state")
    logs_dir: Path = Path("./logs")
    default_repo_path: str = "."
    git_agent_branch_prefix: str = "agent/"

    @property
    def rtk_available(self) -> bool:
        import shutil

        return self.rtk_enabled and shutil.which("rtk") is not None

    def ensure_dirs(self) -> None:
        for d in (self.handoffs_dir, self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


_run_semaphore: _asyncio.Semaphore | None = None


def get_run_semaphore() -> _asyncio.Semaphore:
    """Semaphore global — 1 run actif à la fois."""
    global _run_semaphore
    if _run_semaphore is None:
        _run_semaphore = _asyncio.Semaphore(1)
    return _run_semaphore
