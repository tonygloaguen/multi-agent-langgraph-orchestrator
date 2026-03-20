"""
api/server.py
Interface web de l'orchestrateur multi-agents.
FastAPI + Server-Sent Events pour streaming temps réel.
Lancer : uvicorn api.server:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# Ajouter le projet au PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

app = FastAPI(title="Orchestrateur Multi-Agents", version="1.0.0")

# ─── State en mémoire ────────────────────────────────────────────────────────

_active_run: dict | None = None
_run_history: list[dict] = []
_log_queue: asyncio.Queue = asyncio.Queue()


# ─── Modèles ─────────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    goal: str
    repo_path: str = ""


class RunStatus(BaseModel):
    run_id: str
    status: str
    goal: str
    repo_path: str
    started_at: str
    tasks_total: int = 0
    tasks_completed: int = 0


# ─── Routes API ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    """Sert la page principale."""
    html_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.post("/api/run")
async def start_run(req: RunRequest, background_tasks=None):
    """Démarre un run de l'orchestrateur."""
    global _active_run

    if _active_run and _active_run.get("status") == "running":
        return {"error": "Un run est déjà en cours", "run_id": _active_run["run_id"]}

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    _active_run = {
        "run_id": run_id,
        "status": "running",
        "goal": req.goal,
        "repo_path": req.repo_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tasks_total": 0,
        "tasks_completed": 0,
        "logs": [],
    }

    # Lancer le pipeline dans un thread séparé
    asyncio.create_task(_run_pipeline_async(req.goal, req.repo_path, run_id))

    return {"run_id": run_id, "status": "started"}


@app.get("/api/run/status")
async def get_status():
    """Retourne le statut du run actif."""
    if not _active_run:
        return {"status": "idle"}
    return _active_run


@app.get("/api/run/history")
async def get_history():
    """Retourne l'historique des runs."""
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
                (
                    e.get("task_count", 0)
                    for e in events
                    if e.get("event") == "plan_generated"
                ),
                0,
            )
            status = next(
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
                    "status": "completed"
                    if status == "pipeline_completed"
                    else "failed"
                    if status == "pipeline_failed"
                    else "running",
                    "tasks_completed": completed,
                    "tasks_total": total,
                }
            )

    return {"runs": history}


@app.get("/api/run/logs")
async def stream_logs(request: Request):
    """Stream SSE des logs du run actif."""

    async def event_generator() -> AsyncGenerator[str, None]:
        # Envoyer les logs déjà présents
        if _active_run:
            for log in _active_run.get("logs", []):
                yield f"data: {json.dumps(log)}\n\n"

        # Streamer les nouveaux logs
        while True:
            if await request.is_disconnected():
                break
            try:
                log = await asyncio.wait_for(_log_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(log)}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat pour garder la connexion ouverte
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            except Exception:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/api/run/stop")
async def stop_run():
    """Arrête le run actif."""
    subprocess.run("pkill -f state_machine.py", shell=True)
    if _active_run:
        _active_run["status"] = "stopped"
    return {"status": "stopped"}


# ─── Pipeline async ──────────────────────────────────────────────────────────


async def _run_pipeline_async(goal: str, repo_path: str, run_id: str) -> None:
    """Lance le pipeline dans un subprocess et streame les logs."""
    global _active_run

    await _push_log({"type": "info", "message": f"Démarrage run {run_id}"})

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "orchestrator" / "state_machine_runner.py"),
        "--goal",
        goal,
        "--repo",
        repo_path or "",
        "--run-id",
        run_id,
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
            raise RuntimeError("Le flux stdout du subprocess est indisponible")

        async for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
                await _push_log({"type": "log", "message": clean})

        await proc.wait()
        status = "completed" if proc.returncode == 0 else "failed"

    except Exception as e:
        await _push_log({"type": "error", "message": str(e)})
        status = "failed"

    if _active_run:
        _active_run["status"] = status

    await _push_log({"type": "done", "status": status})

    if _active_run:
        _run_history.insert(0, {**_active_run})


async def _push_log(entry: dict) -> None:
    """Ajoute un log à la queue SSE et à l'historique du run actif."""
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    if _active_run:
        _active_run.setdefault("logs", []).append(entry)
    await _log_queue.put(entry)


# ─── Point d'entrée ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
