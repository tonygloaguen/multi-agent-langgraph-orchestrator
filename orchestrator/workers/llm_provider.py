"""orchestrator/workers/llm_provider.py

Abstraction multi-provider pour les appels LLM.
Détection de rate limit, fallback automatique, logging structuré JSONL.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ─── Enums ───────────────────────────────────────────────────────────────────


class ProviderStatus(str, Enum):
    """Statut normalisé d'un appel provider."""

    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    BINARY_NOT_FOUND = "binary_not_found"
    TIMEOUT = "timeout"
    INTERACTIVE_BLOCKED = "interactive_blocked"
    EMPTY_OUTPUT = "empty_output"
    UNKNOWN_ERROR = "unknown_error"


class PipelineStatus(str, Enum):
    """Statut final du pipeline."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"
    FALLBACK = "fallback"


# ─── Data structures ──────────────────────────────────────────────────────────


@dataclass
class ProviderResult:
    """Résultat normalisé d'un appel LLM provider."""

    provider: str
    status: ProviderStatus
    output: str = ""
    rc: int = 0
    stdout: str = ""
    stderr: str = ""
    reset_time: str | None = None
    error_reason: str = ""
    cmd: list[str] = field(default_factory=list)
    cwd: str = "."

    @property
    def is_ok(self) -> bool:
        return self.status == ProviderStatus.SUCCESS

    @property
    def raw_excerpt(self) -> str:
        combined = (self.stdout + "\n" + self.stderr).strip()
        return combined[:400]


@dataclass
class ProviderConfig:
    """Configuration d'un provider LLM."""

    name: str
    bin_path: str | None = None       # Chemin binaire CLI
    api_key_env: str | None = None    # Variable d'env pour la clé API
    model: str | None = None
    timeout: int = 120
    extra_args: list[str] = field(default_factory=list)


class LLMInvocationError(RuntimeError):
    """Erreur normalisée lors d'un appel LLM — sous-classe RuntimeError pour compat."""

    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        super().__init__(
            f"[{result.provider}] {result.status.value}: {result.error_reason}"
        )


# ─── Rate limit & interactive detection ──────────────────────────────────────

_RATE_LIMIT_PATTERNS = [
    r"you'?ve hit your limit",
    r"rate[\s\-]?limit",
    r"/rate-limit-options",
    r"resets?\s+\d",
    r"resets?\s+at",
    r"usage limit",
]

_RESET_TIME_RE = re.compile(
    r"resets?\s+(?:at\s+)?(\d+(?::\d+)?(?:am|pm)?(?:\s*\([^)]+\))?)",
    re.IGNORECASE,
)

_INTERACTIVE_PATTERNS = [
    r"what do you want to do",
    r"stop and wait",
    r"switch to extra usage",
    r"^\d+\.\s+stop",
    r"upgrade your plan",
]


def _is_rate_limited(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in _RATE_LIMIT_PATTERNS)


def _is_interactive_prompt(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.MULTILINE) for p in _INTERACTIVE_PATTERNS)


def _extract_reset_time(text: str) -> str | None:
    m = _RESET_TIME_RE.search(text)
    return m.group(1).strip() if m else None


# ─── Error parsing ────────────────────────────────────────────────────────────


def parse_provider_error(
    provider: str,
    rc: int,
    stdout: str,
    stderr: str,
    cmd: list[str],
    cwd: str,
    exc: Exception | None = None,
) -> ProviderResult:
    """Analyse la sortie d'un provider CLI et retourne un ProviderResult normalisé.

    Args:
        provider: Nom du provider (claude, gemini, …).
        rc: Code de retour subprocess.
        stdout: Sortie standard capturée.
        stderr: Sortie d'erreur capturée.
        cmd: Commande réellement exécutée.
        cwd: Répertoire de travail.
        exc: Exception subprocess si applicable.

    Returns:
        ProviderResult avec status normalisé.
    """
    combined = (stdout + "\n" + stderr).strip()

    if exc is not None:
        if isinstance(exc, subprocess.TimeoutExpired):
            return ProviderResult(
                provider=provider,
                status=ProviderStatus.TIMEOUT,
                rc=-1,
                stdout=stdout,
                stderr=stderr,
                error_reason=f"Timeout après {exc.timeout}s",
                cmd=cmd,
                cwd=cwd,
            )
        if isinstance(exc, FileNotFoundError):
            bin_name = cmd[0] if cmd else "?"
            return ProviderResult(
                provider=provider,
                status=ProviderStatus.BINARY_NOT_FOUND,
                rc=-1,
                error_reason=f"Binaire introuvable : {bin_name}",
                cmd=cmd,
                cwd=cwd,
            )

    # Claude écrit le rate limit dans stdout, pas stderr
    if _is_rate_limited(combined):
        reset_time = _extract_reset_time(combined)
        return ProviderResult(
            provider=provider,
            status=ProviderStatus.RATE_LIMITED,
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            reset_time=reset_time,
            error_reason=(
                f"Rate limit atteint{f' — reset {reset_time}' if reset_time else ''}"
            ),
            cmd=cmd,
            cwd=cwd,
        )

    if rc != 0 and _is_interactive_prompt(combined):
        return ProviderResult(
            provider=provider,
            status=ProviderStatus.INTERACTIVE_BLOCKED,
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            error_reason="Mode interactif non supporté en subprocess",
            cmd=cmd,
            cwd=cwd,
        )

    if rc == 0 and not stdout.strip():
        return ProviderResult(
            provider=provider,
            status=ProviderStatus.EMPTY_OUTPUT,
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            error_reason="Réponse vide",
            cmd=cmd,
            cwd=cwd,
        )

    if rc != 0:
        return ProviderResult(
            provider=provider,
            status=ProviderStatus.UNKNOWN_ERROR,
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            error_reason=f"rc={rc}: {combined[:200]}",
            cmd=cmd,
            cwd=cwd,
        )

    return ProviderResult(
        provider=provider,
        status=ProviderStatus.SUCCESS,
        output=stdout.strip(),
        rc=0,
        stdout=stdout,
        stderr=stderr,
        cmd=cmd,
        cwd=cwd,
    )


# ─── Provider implementations ─────────────────────────────────────────────────


def _call_claude_provider(
    config: ProviderConfig, prompt: str, cwd: str
) -> ProviderResult:
    """Appelle Claude Code CLI en mode non-interactif."""
    bin_path = config.bin_path or "/home/gloaguen/.local/bin/claude"
    cmd = [bin_path, "--print", "--output-format", "text"] + config.extra_args

    effective_cwd = cwd if Path(cwd).is_dir() else "."
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            cwd=effective_cwd,
        )
        return parse_provider_error(
            "claude", proc.returncode, proc.stdout, proc.stderr, cmd, effective_cwd
        )
    except subprocess.TimeoutExpired as exc:
        return parse_provider_error("claude", -1, "", "", cmd, effective_cwd, exc)
    except FileNotFoundError as exc:
        return parse_provider_error("claude", -1, "", "", cmd, effective_cwd, exc)


def _call_gemini_provider(
    config: ProviderConfig, prompt: str, _cwd: str
) -> ProviderResult:
    """Appelle Gemini via l'API Google GenAI (langchain)."""
    import os

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return ProviderResult(
            provider="gemini",
            status=ProviderStatus.UNKNOWN_ERROR,
            error_reason="GEMINI_API_KEY manquante",
        )

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = config.model or "gemini-2.0-flash"
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            max_output_tokens=4096,
        )
        response = llm.invoke(prompt)
        output: str = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )

        if not output.strip():
            return ProviderResult(
                provider="gemini",
                status=ProviderStatus.EMPTY_OUTPUT,
                error_reason="Réponse Gemini vide",
            )

        return ProviderResult(
            provider="gemini",
            status=ProviderStatus.SUCCESS,
            output=output.strip(),
            rc=0,
            stdout=output,
        )
    except Exception as exc:
        return ProviderResult(
            provider="gemini",
            status=ProviderStatus.UNKNOWN_ERROR,
            error_reason=str(exc)[:300],
        )


# ─── Public API ───────────────────────────────────────────────────────────────

_LogEventFn = Callable[[str, str, dict[str, Any], Path], None]


def _default_providers() -> list[ProviderConfig]:
    """Ordre de fallback par défaut."""
    return [
        ProviderConfig(name="claude", timeout=120),
        ProviderConfig(name="gemini", model="gemini-2.0-flash", timeout=60),
    ]


def call_llm(
    provider_config: ProviderConfig,
    prompt: str,
    cwd: str = ".",
) -> ProviderResult:
    """Appelle un provider LLM et retourne un ProviderResult normalisé.

    Args:
        provider_config: Configuration du provider.
        prompt: Prompt à envoyer.
        cwd: Répertoire de travail (pertinent pour les providers CLI).

    Returns:
        ProviderResult avec status normalisé.
    """
    name = provider_config.name
    if name == "claude":
        return _call_claude_provider(provider_config, prompt, cwd)
    elif name == "gemini":
        return _call_gemini_provider(provider_config, prompt, cwd)
    return ProviderResult(
        provider=name,
        status=ProviderStatus.UNKNOWN_ERROR,
        error_reason=f"Provider inconnu : {name}",
    )


def call_llm_with_fallback(
    prompt: str,
    cwd: str = ".",
    run_id: str = "",
    log_event_fn: _LogEventFn | None = None,
    log_dir: Path | None = None,
    providers: list[ProviderConfig] | None = None,
) -> ProviderResult:
    """Appelle les providers LLM dans l'ordre avec fallback automatique.

    Journalise chaque tentative (provider_invoked, provider_rate_limited,
    provider_failed, fallback_started, fallback_succeeded).

    Args:
        prompt: Prompt à envoyer.
        cwd: Répertoire de travail.
        run_id: Identifiant du run pour le journal.
        log_event_fn: Fonction de journalisation JSONL.
        log_dir: Dossier du journal.
        providers: Liste ordonnée de providers. Défaut : claude → gemini.

    Returns:
        ProviderResult du premier provider ayant répondu, ou dernier échec.
    """
    if providers is None:
        providers = _default_providers()

    last_result: ProviderResult | None = None

    def _log(event: str, data: dict[str, Any]) -> None:
        if log_event_fn and log_dir and run_id:
            log_event_fn(run_id, event, data, log_dir)

    for i, config in enumerate(providers):
        _log("provider_invoked", {"provider": config.name, "cwd": cwd})

        result = call_llm(config, prompt, cwd)
        last_result = result

        if result.is_ok:
            if i > 0:
                _log(
                    "fallback_succeeded",
                    {
                        "provider": config.name,
                        "output_length": len(result.output),
                    },
                )
            return result

        # Log the specific failure
        event_data: dict[str, Any] = {
            "provider": config.name,
            "rc": result.rc,
            "status": result.status.value,
            "error_reason": result.error_reason,
            "raw_output_excerpt": result.raw_excerpt,
        }

        if result.status == ProviderStatus.RATE_LIMITED:
            if result.reset_time:
                event_data["reset_time_utc"] = result.reset_time
            _log("provider_rate_limited", event_data)
        else:
            _log("provider_failed", event_data)

        # Announce fallback if next provider exists
        remaining = providers[i + 1 :]
        if remaining:
            _log(
                "fallback_started",
                {
                    "from_provider": config.name,
                    "to_provider": remaining[0].name,
                    "reason": result.status.value,
                },
            )

    return last_result or ProviderResult(
        provider="none",
        status=ProviderStatus.UNKNOWN_ERROR,
        error_reason="Aucun provider disponible",
    )
