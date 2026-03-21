from __future__ import annotations

import asyncio as _asyncio
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM API keys (SecretStr : jamais affichées dans les logs) ────────────
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")

    # ── Modèles ───────────────────────────────────────────────────────────────
    claude_model: str = "claude-opus-4-6"
    codex_model: str = "codex-mini-latest"
    gemini_model: str = "gemini-2.0-flash"

    # ── Comportement orchestrateur ────────────────────────────────────────────
    orchestrator_max_repair_loops: int = Field(default=2, ge=1, le=5)
    orchestrator_task_timeout: int = Field(default=300, ge=30)
    orchestrator_context_max_tokens: int = Field(default=8000, ge=1000)
    gemini_fallback_enabled: bool = True
    rtk_enabled: bool = True

    # ── Répertoires ───────────────────────────────────────────────────────────
    handoffs_dir: Path = Path("./orchestrator/handoffs")
    state_dir: Path = Path("./orchestrator/state")
    logs_dir: Path = Path("./logs")
    default_repo_path: str = "."
    git_agent_branch_prefix: str = "agent/"

    # ── Authentification API (RBAC) ───────────────────────────────────────────
    # AUTH_ENABLED=false désactive l'auth (dev local uniquement, jamais en prod)
    auth_enabled: bool = True
    api_token_admin: SecretStr | None = None
    api_token_operator: SecretStr | None = None
    api_token_reader: SecretStr | None = None

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Liste d'origines séparées par virgule. "*" autorisé seulement en dev.
    cors_allowed_origins: str = "http://localhost:8080"

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_run: str = "5/minute"
    rate_limit_default: str = "60/minute"

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def rtk_available(self) -> bool:
        import shutil

        return self.rtk_enabled and shutil.which("rtk") is not None

    @property
    def anthropic_api_key_value(self) -> str:
        return self.anthropic_api_key.get_secret_value()

    @property
    def openai_api_key_value(self) -> str:
        return self.openai_api_key.get_secret_value()

    @property
    def gemini_api_key_value(self) -> str:
        return self.gemini_api_key.get_secret_value()

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
