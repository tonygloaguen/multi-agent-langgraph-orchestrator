"""
api/server.py
Interface web de l'orchestrateur multi-agents.
FastAPI + Server-Sent Events pour streaming temps réel.

Sécurité :
  - Authentification Bearer (RBAC : admin / operator / reader)
  - Rate limiting par IP (slowapi)
  - Headers de sécurité HTTP
  - CORS restreint (origines configurables via CORS_ALLOWED_ORIGINS)
  - Audit log HMAC-SHA256 de tous les accès HTTP dans logs/audit.jsonl
  - Validation / sanitisation des entrées (anti prompt-injection)

Lancer : uvicorn api.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.security import Role, require_roles, sanitize_goal, sanitize_repo_path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Rate limiter ──────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orchestrateur Multi-Agents",
    version="1.0.0",
    # Swagger désactivé hors mode debug (moins de surface d'attaque)
    docs_url="/docs" if os.getenv("DEBUG", "false").lower() == "true" else None,
    redoc_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── CORS ──────────────────────────────────────────────────────────────────────


def _get_cors_origins() -> list[str]:
    from orchestrator.config import get_settings

    raw = get_settings().cors_allowed_origins
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── State en mémoire ──────────────────────────────────────────────────────────

_active_run: dict | None = None
_run_history: list[dict] = []
_log_queue: asyncio.Queue = asyncio.Queue()

# ── Audit log HMAC ────────────────────────────────────────────────────────────

_AUDIT_KEY: bytes | None = None


def _get_audit_key() -> bytes:
    global _AUDIT_KEY
    if _AUDIT_KEY:
        return _AUDIT_KEY
    key_file = PROJECT_ROOT / ".orchestrator_signing_key"
    if key_file.exists():
        _AUDIT_KEY = key_file.read_bytes()
    else:
        _AUDIT_KEY = secrets.token_bytes(32)
        key_file.write_bytes(_AUDIT_KEY)
        key_file.chmod(0o600)
    return _AUDIT_KEY


def _sign(entry: dict) -> str:
    key = _get_audit_key()
    payload = json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _write_audit_log(entry: dict) -> None:
    """Écrit une entrée d'audit signée HMAC dans logs/audit.jsonl.

    Ne journalise jamais les valeurs d'Authorization ni les secrets.
    """
    entry["sig"] = _sign({k: v for k, v in entry.items() if k != "sig"})
    audit_path = PROJECT_ROOT / "logs" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Middlewares ───────────────────────────────────────────────────────────────


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Ajoute les headers de sécurité HTTP à toutes les réponses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    )
    response.headers.pop("server", None)
    return response


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """Journalise les accès HTTP dans logs/audit.jsonl (HMAC-SHA256).

    Journalise : méthode, chemin, statut, IP, rôle, durée.
    Ne journalise PAS : valeur du token Bearer, corps de requête.
    """
    start = datetime.now(timezone.utc)
    client_ip = request.client.host if request.client else "unknown"

    response = await call_next(request)

    duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    role_val = getattr(request.state, "role", None)
    role_str = role_val.value if isinstance(role_val, Role) else "unauthenticated"

    entry: dict = {
        "ts": start.isoformat(),
        "type": "http_access",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "client_ip": client_ip,
        "role": role_str,
        "duration_ms": duration_ms,
    }

    if response.status_code == 401:
        entry["security_event"] = "auth_failure"
    elif response.status_code == 403:
        entry["security_event"] = "authz_failure"
    elif response.status_code == 429:
        entry["security_event"] = "rate_limit_exceeded"

    _write_audit_log(entry)
    return response


# ── Modèles ───────────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    goal: str
    repo_path: str = ""


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Page principale (accessible sans auth)."""
    html_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.post("/api/run", dependencies=[Depends(require_roles(Role.admin, Role.operator))])
@limiter.limit(lambda: _get_run_limit())
async def start_run(request: Request, req: RunRequest) -> dict:
    """Démarre un run. Rôle minimum : operator.

    Rate limit : RATE_LIMIT_RUN (défaut 5/minute par IP).
    """
    global _active_run

    goal = sanitize_goal(req.goal)
    repo_path = sanitize_repo_path(req.repo_path)

    if _active_run and _active_run.get("status") == "running":
        return {"error": "Un run est déjà en cours", "run_id": _active_run["run_id"]}

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    _active_run = {
        "run_id": run_id,
        "status": "running",
        "goal": goal,
        "repo_path": repo_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tasks_total": 0,
        "tasks_completed": 0,
        "logs": [],
    }

    asyncio.create_task(_run_pipeline_async(goal, repo_path, run_id))
    return {"run_id": run_id, "status": "started"}


@app.get(
    "/api/run/status",
    dependencies=[Depends(require_roles(Role.admin, Role.operator, Role.reader))],
)
@limiter.limit(lambda: _get_default_limit())
async def get_status(request: Request) -> dict:
    """Statut du run actif. Accessible à tous les rôles authentifiés."""
    if not _active_run:
        return {"status": "idle"}
    return {k: v for k, v in _active_run.items() if k != "logs"}


@app.get(
    "/api/run/history",
    dependencies=[Depends(require_roles(Role.admin, Role.operator, Role.reader))],
)
@limiter.limit(lambda: _get_default_limit())
async def get_history(request: Request) -> dict:
    """Historique des 20 derniers runs."""
    history = []
    log_dir = PROJECT_ROOT / "orchestrator" / "state" / "runs"
    if log_dir.exists():
        for f in sorted(log_dir.glob("*.jsonl"), reverse=True)[:20]:
            events = []
            try:
                for line in f.read_text().splitlines():
                    if line.strip():
                        events.append(json.loads(line))
            except Exception:
                continue

            if not events:
                continue

            first = events[0]
            completed = sum(1 for e in events if e.get("event") == "task_completed")
            total = next(
                (e.get("task_count", 0) for e in events if e.get("event") == "plan_generated"),
                0,
            )
            status_evt = next(
                (
                    e.get("event")
                    for e in reversed(events)
                    if e.get("event") in ("pipeline_completed", "pipeline_failed")
                ),
                "running",
            )

            history.append(
                {
                    "run_id": first.get("run_id", f.stem),
                    "started_at": first.get("ts", ""),
                    "goal": first.get("goal", ""),
                    "repo_path": first.get("repo_path", ""),
                    "status": (
                        "completed"
                        if status_evt == "pipeline_completed"
                        else "failed"
                        if status_evt == "pipeline_failed"
                        else "running"
                    ),
                    "tasks_completed": completed,
                    "tasks_total": total,
                }
            )

    return {"runs": history}


@app.get(
    "/api/run/logs",
    dependencies=[Depends(require_roles(Role.admin, Role.operator, Role.reader))],
)
@limiter.limit(lambda: _get_default_limit())
async def stream_logs(request: Request) -> StreamingResponse:
    """Stream SSE des logs du run actif."""

    async def event_generator() -> AsyncGenerator[str, None]:
        if _active_run:
            for log in _active_run.get("logs", []):
                yield f"data: {json.dumps(log)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                log = await asyncio.wait_for(_log_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(log)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            except Exception:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/run/stop", dependencies=[Depends(require_roles(Role.admin))])
@limiter.limit("10/minute")
async def stop_run(request: Request) -> dict:
    """Arrête le run actif. Rôle minimum : admin."""
    subprocess.run(["pkill", "-f", "state_machine.py"], check=False)
    if _active_run:
        _active_run["status"] = "stopped"
    return {"status": "stopped"}


# ── Helpers rate limit (lazy depuis config) ───────────────────────────────────


def _get_run_limit() -> str:
    try:
        from orchestrator.config import get_settings

        cfg = get_settings()
        return cfg.rate_limit_run if cfg.rate_limit_enabled else "10000/minute"
    except Exception:
        return "5/minute"


def _get_default_limit() -> str:
    try:
        from orchestrator.config import get_settings

        cfg = get_settings()
        return cfg.rate_limit_default if cfg.rate_limit_enabled else "10000/minute"
    except Exception:
        return "60/minute"


# ── Pipeline async ────────────────────────────────────────────────────────────


async def _run_pipeline_async(goal: str, repo_path: str, run_id: str) -> None:
    global _active_run

    await _push_log({"type": "info", "message": f"Démarrage run {run_id}"})

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "orchestrator" / "state_machine_runner.py"),
        "--goal", goal,
        "--repo", repo_path or "",
        "--run-id", run_id,
    ]

    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        if proc.stdout is None:
            raise RuntimeError("flux stdout indisponible")

        async for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
                await _push_log({"type": "log", "message": clean})

        await proc.wait()
        final_status = "completed" if proc.returncode == 0 else "failed"

    except Exception as e:
        await _push_log({"type": "error", "message": str(e)})
        final_status = "failed"

    if _active_run:
        _active_run["status"] = final_status

    await _push_log({"type": "done", "status": final_status})

    if _active_run:
        _run_history.insert(0, {**_active_run})


async def _push_log(entry: dict) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    if _active_run:
        _active_run.setdefault("logs", []).append(entry)
    await _log_queue.put(entry)


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
