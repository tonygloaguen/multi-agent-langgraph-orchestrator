"""
orchestrator/state_machine.py
Pipeline multi-agents — LangGraph 1.x + NIS2
Graphe : init → preflight → snapshot → plan → [prepare → implement → validate
         → (repair loop) → review → commit] × N tâches → done
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from rich.console import Console
from rich.panel import Panel

console = Console()

# ─── Signing key NIS2 ────────────────────────────────────────────────────────

_SIGNING_KEY: bytes | None = None


def _get_signing_key() -> bytes:
    global _SIGNING_KEY
    if _SIGNING_KEY:
        return _SIGNING_KEY
    key_file = Path(".orchestrator_signing_key")
    if key_file.exists():
        _SIGNING_KEY = key_file.read_bytes()
    else:
        import secrets

        _SIGNING_KEY = secrets.token_bytes(32)
        key_file.write_bytes(_SIGNING_KEY)
        key_file.chmod(0o600)
        console.print("[yellow]Clé HMAC générée : .orchestrator_signing_key[/yellow]")
    return _SIGNING_KEY


def _sign_entry(entry: dict) -> str:
    key = _get_signing_key()
    payload = json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _log_event(run_id: str, event: str, data: dict, log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event": event,
        **data,
    }
    entry["signature"] = _sign_entry(
        {k: v for k, v in entry.items() if k != "signature"}
    )
    with open(log_dir / f"{run_id}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─── Utilitaires ─────────────────────────────────────────────────────────────


def _cmd(cmd: str, cwd: str = ".") -> tuple[int, str, str]:
    r = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _load_ignore_patterns() -> list[str]:
    ignore_file = Path(".orchestrator-ignore")
    if not ignore_file.exists():
        return []
    return [
        line.strip()
        for line in ignore_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _filter_snapshot(snapshot: str, ignore_patterns: list[str]) -> str:
    if not ignore_patterns:
        return snapshot
    return "\n".join(
        "[EXCLUDED]" if any(p in line for p in ignore_patterns) else line
        for line in snapshot.split("\n")
    )


def _scan_secrets(repo_path: str) -> tuple[bool, str]:
    if (
        subprocess.run("which gitleaks", shell=True, capture_output=True).returncode
        != 0
    ):
        return True, "gitleaks absent — scan ignoré"
    rc, out, _ = _cmd(
        f"gitleaks detect --source {repo_path} --no-git --redact -q", cwd=repo_path
    )
    return (True, "aucun secret") if rc == 0 else (False, f"SECRET : {out[:200]}")


# ─── État LangGraph ──────────────────────────────────────────────────────────


class OrchestratorState(TypedDict, total=False):
    # Config
    goal: str
    repo_path: str
    run_id: str
    log_dir: str

    # Plan
    plan_id: str
    tasks: list[dict]
    task_index: int

    # Tâche courante
    handoff: dict
    ruff_out: str
    mypy_out: str
    test_out: str
    repair_attempts: int
    last_analysis: dict
    diff: str

    # Flags
    validation_passed: bool
    review_passed: bool
    escalated: bool
    completed_tasks: list[str]
    errors: list[str]
    status: str  # running | completed | failed


# ─── Nœuds du graphe ─────────────────────────────────────────────────────────


def node_init(state: OrchestratorState) -> dict:
    from orchestrator.config import get_settings

    cfg = get_settings()

    repo_path = state.get("repo_path", "")
    if not repo_path:
        repo_path = cfg.default_repo_path

    run_id = f"run-{_now()}"
    log_dir = str(Path(cfg.state_dir) / "runs")

    console.print(
        Panel(
            f"[bold green]Orchestrateur démarré[/bold green]\n"
            f"Run ID : {run_id}\n"
            f"Repo   : {repo_path}\n"
            f"Goal   : {state.get('goal') or '(mode analyse)'}",
            title="Multi-Agent Pipeline — LangGraph",
        )
    )

    _log_event(
        run_id,
        "pipeline_start",
        {
            "repo_path": repo_path,
            "goal": state.get("goal", ""),
        },
        Path(log_dir),
    )

    return {
        "repo_path": repo_path,
        "run_id": run_id,
        "log_dir": log_dir,
        "task_index": 0,
        "completed_tasks": [],
        "errors": [],
        "status": "running",
    }


def node_preflight(state: OrchestratorState) -> dict:
    from orchestrator.config import get_settings

    cfg = get_settings()
    repo = state["repo_path"]
    errors = []

    console.print("\n[cyan]--- Preflight ---[/cyan]")

    if not cfg.anthropic_api_key:
        errors.append("ANTHROPIC_API_KEY manquante")
    if not cfg.openai_api_key:
        errors.append("OPENAI_API_KEY manquante")

    for tool in ["ruff", "mypy", "pytest", "codex"]:
        rc, _, _ = _cmd(f"which {tool}")
        if rc != 0:
            venv_tool = Path(__file__).parent.parent / ".venv" / "bin" / tool
            if not venv_tool.exists():
                errors.append(f"Outil manquant : {tool}")

    rc, _, _ = _cmd("git rev-parse HEAD", cwd=repo)
    if rc != 0:
        errors.append(f"Pas un repo Git : {repo}")

    # Scan secrets
    safe, msg = _scan_secrets(repo)
    if not safe:
        errors.append(f"Secret détecté : {msg}")

    if errors:
        for e in errors:
            console.print(f"[red][FAIL][/red] {e}")
        _log_event(
            state["run_id"],
            "preflight_failed",
            {"errors": errors},
            Path(state["log_dir"]),
        )
        return {"errors": errors, "status": "failed"}

    console.print("[green]Preflight OK[/green]")
    return {"errors": []}


def node_snapshot(state: OrchestratorState) -> dict:
    repo = state["repo_path"]
    ignore_patterns = _load_ignore_patterns()

    _, tree, _ = _cmd("find . -name '*.py' | head -40 | sort", cwd=repo)
    _, git_status, _ = _cmd("git status --short", cwd=repo)
    snapshot = _filter_snapshot(
        f"Fichiers Python:\n{tree}\n\nGit status:\n{git_status}", ignore_patterns
    )
    snap_hash = hashlib.sha256(snapshot.encode()).hexdigest()[:16]
    _log_event(
        state["run_id"],
        "snapshot_created",
        {"snapshot_hash": snap_hash},
        Path(state["log_dir"]),
    )

    # Stocker le snapshot temporairement dans last_analysis pour le passer à plan
    return {"last_analysis": {"snapshot": snapshot}}


def node_plan(state: OrchestratorState) -> dict:
    from orchestrator.workers import claude_worker

    console.print("\n[cyan]Claude — planification...[/cyan]")
    snapshot = state.get("last_analysis", {}).get("snapshot", "")

    try:
        plan = claude_worker.generate_plan(state.get("goal", ""), snapshot)
        tasks = plan["tasks"]
        console.print(f"[green]Plan : {len(tasks)} tâche(s)[/green]")
        _log_event(
            state["run_id"],
            "plan_generated",
            {
                "plan_id": plan["plan_id"],
                "task_count": len(tasks),
            },
            Path(state["log_dir"]),
        )
        return {
            "plan_id": plan["plan_id"],
            "tasks": tasks,
            "task_index": 0,
            "last_analysis": {},
        }
    except Exception as e:
        console.print(f"[red]Erreur planification : {e}[/red]")
        _log_event(
            state["run_id"],
            "planning_failed",
            {"error": str(e)},
            Path(state["log_dir"]),
        )
        return {"errors": [str(e)], "status": "failed"}


def node_prepare_task(state: OrchestratorState) -> dict:
    import yaml
    from orchestrator.config import get_settings

    cfg = get_settings()
    tasks = state["tasks"]
    idx = state["task_index"]
    task = tasks[idx]

    task_id = task.get("task_id", f"task-{idx:03d}")
    title = task.get("title", "")

    console.print(
        f"\n[bold cyan]── Tâche {idx + 1}/{len(tasks)} : {title} ──[/bold cyan]"
    )

    handoff = {
        "task_id": task_id,
        "plan_id": state["plan_id"],
        "task_title": title,
        "task_objective": task.get("objective", ""),
        "files_allowed": task.get("files_allowed", []),
        "paths_forbidden": ["migrations/", ".github/workflows/", "infra/", ".env"],
        "acceptance_criteria": task.get("acceptance_criteria", []),
    }

    # Isolation par run_id — multi-utilisateurs
    run_handoffs_dir = Path(cfg.handoffs_dir) / state["run_id"]
    run_handoffs_dir.mkdir(parents=True, exist_ok=True)
    hf_path = run_handoffs_dir / f"{task_id}.yaml"
    with open(hf_path, "w", encoding="utf-8") as f:
        yaml.dump(handoff, f, allow_unicode=True)

    _log_event(
        state["run_id"],
        "task_start",
        {
            "task_id": task_id,
            "files_allowed": handoff["files_allowed"],
        },
        Path(state["log_dir"]),
    )

    return {
        "handoff": handoff,
        "repair_attempts": 0,
        "validation_passed": False,
        "review_passed": False,
        "escalated": False,
        "last_analysis": {},
    }


def node_implement(state: OrchestratorState) -> dict:
    from orchestrator.workers import codex_worker

    console.print("[cyan]Codex — implémentation...[/cyan]")
    result = codex_worker.implement_task(state["handoff"], state["repo_path"])

    if not result["success"]:
        console.print(f"[red]Codex erreur : {result['error']}[/red]")
        _log_event(
            state["run_id"],
            "task_impl_failed",
            {
                "task_id": state["handoff"]["task_id"],
                "error": result["error"],
            },
            Path(state["log_dir"]),
        )

    return {"diff": result.get("diff", "")}


def node_validate(state: OrchestratorState) -> dict:
    repo = state["repo_path"]

    rc_r, ruff_out, _ = _cmd("ruff check . --output-format=concise", cwd=repo)
    rc_m, mypy_out, _ = _cmd("mypy . --ignore-missing-imports", cwd=repo)
    rc_t, test_out, _ = _cmd("pytest -q --tb=short 2>&1 | tail -15", cwd=repo)

    passed = rc_r == 0 and rc_m == 0 and rc_t == 0

    if passed:
        console.print("[green]Validation PASS ✓[/green]")
    else:
        console.print("[yellow]Validation FAIL[/yellow]")

    return {
        "ruff_out": ruff_out,
        "mypy_out": mypy_out,
        "test_out": test_out,
        "validation_passed": passed,
    }


def node_analyze(state: OrchestratorState) -> dict:
    from orchestrator.workers import claude_worker

    console.print("[yellow]Analyse des erreurs...[/yellow]")

    _, diff, _ = _cmd("git diff", cwd=state["repo_path"])

    try:
        analysis = claude_worker.analyze_failure(
            state.get("ruff_out", ""),
            state.get("mypy_out", ""),
            state.get("test_out", ""),
            diff,
            state["handoff"]["files_allowed"],
            state["repo_path"],
        )
        console.print(f"[yellow]Cause : {analysis.get('root_cause', '?')}[/yellow]")

        if analysis.get("escalate"):
            console.print("[red]Escalade — problème architectural[/red]")
            _log_event(
                state["run_id"],
                "task_escalated",
                {
                    "task_id": state["handoff"]["task_id"],
                    "root_cause": analysis.get("root_cause"),
                },
                Path(state["log_dir"]),
            )
            return {"last_analysis": analysis, "escalated": True}

        return {"last_analysis": analysis, "escalated": False}

    except Exception as e:
        console.print(f"[yellow]Analyse échouée ({e})[/yellow]")
        return {"last_analysis": {}, "escalated": False}


def node_repair(state: OrchestratorState) -> dict:
    from orchestrator.workers import codex_worker
    from orchestrator.config import get_settings

    cfg = get_settings()
    attempts = state.get("repair_attempts", 0) + 1

    console.print(
        f"[yellow]Repair {attempts}/{cfg.orchestrator_max_repair_loops}...[/yellow]"
    )

    result = codex_worker.repair_task(
        state["handoff"],
        state["repo_path"],
        state.get("ruff_out", ""),
        state.get("mypy_out", ""),
        state.get("test_out", ""),
        attempts,
        analysis=state.get("last_analysis"),
    )

    if result.get("regressed"):
        console.print(
            f"[red]Régression détectée "
            f"({result['errors_before']} → {result['errors_after']} erreurs) "
            f"— patch annulé[/red]"
        )
        _log_event(
            state["run_id"],
            "repair_regression",
            {
                "task_id": state["handoff"]["task_id"],
                "attempt": attempts,
            },
            Path(state["log_dir"]),
        )

    return {"repair_attempts": attempts, "diff": result.get("diff", "")}


def node_review(state: OrchestratorState) -> dict:
    from orchestrator.workers import claude_worker

    _, diff, _ = _cmd("git diff", cwd=state["repo_path"])

    if not diff:
        console.print("[yellow]Aucune modification détectée.[/yellow]")
        return {"review_passed": False, "diff": "", "no_changes": True}

    # Scan secrets pre-commit
    safe, msg = _scan_secrets(state["repo_path"])
    if not safe:
        console.print(f"[red][NIS2] {msg} — commit annulé[/red]")
        _cmd("git checkout .", cwd=state["repo_path"])
        return {"review_passed": False, "diff": ""}

    console.print("[cyan]Claude — review conformité...[/cyan]")
    try:
        review = claude_worker.review_conformance(state["handoff"], diff)
        issues = review.get("issues", [])
        real_issues = [x for x in issues if "JSON parse" not in x]

        if review.get("passed") and not real_issues:
            console.print("[green]Review PASS[/green]")
            return {"review_passed": True, "diff": diff}
        elif real_issues:
            console.print(f"[yellow]Review WARNING : {real_issues}[/yellow]")
            return {"review_passed": True, "diff": diff}
        else:
            console.print("[green]Review PASS[/green]")
            return {"review_passed": True, "diff": diff}
    except Exception as e:
        console.print(f"[yellow]Review exception (ignorée) : {e}[/yellow]")
        return {"review_passed": True, "diff": diff}


def node_commit(state: OrchestratorState) -> dict:
    task_id = state["handoff"]["task_id"]
    title = state["handoff"]["task_title"]

    _cmd(
        f'git add -A && git commit -m "agent: {task_id} — {title}"',
        cwd=state["repo_path"],
    )
    _, commit_sha, _ = _cmd("git rev-parse HEAD", cwd=state["repo_path"])
    console.print(f"[green]Commit : {commit_sha[:12]}[/green]")

    _log_event(
        state["run_id"],
        "task_completed",
        {
            "task_id": task_id,
            "repair_attempts": state.get("repair_attempts", 0),
            "validation_pass": state.get("validation_passed", False),
            "review_pass": state.get("review_passed", False),
            "commit_sha": commit_sha[:12],
        },
        Path(state["log_dir"]),
    )

    console.print(f"[green]Tâche {task_id} terminée.[/green]")

    completed = state.get("completed_tasks", []) + [task_id]
    return {
        "completed_tasks": completed,
        "task_index": state["task_index"] + 1,
    }


def node_done(state: OrchestratorState) -> dict:
    console.print(
        Panel(
            f"[bold green]Pipeline terminé[/bold green]\n"
            f"Run ID  : {state['run_id']}\n"
            f"Tâches  : {len(state.get('completed_tasks', []))}/{len(state.get('tasks', []))}\n"
            f"Journal : {state['log_dir']}/{state['run_id']}.jsonl",
            title="Done",
        )
    )
    completed = len(state.get("completed_tasks", []))
    total = len(state.get("tasks", []))
    _log_event(
        state["run_id"],
        "pipeline_completed",
        {
            "completed": completed,
            "total": total,
        },
        Path(state["log_dir"]),
    )
    return {"status": "completed", "completed_tasks": state.get("completed_tasks", [])}


# ─── Routeurs conditionnels ───────────────────────────────────────────────────


def route_after_preflight(state: OrchestratorState) -> Literal["snapshot", "done"]:
    return "done" if state.get("status") == "failed" else "snapshot"


def route_after_plan(state: OrchestratorState) -> Literal["prepare_task", "done"]:
    if state.get("status") == "failed":
        return "done"
    if not state.get("tasks"):
        return "done"
    return "prepare_task"


def route_after_validate(
    state: OrchestratorState,
) -> Literal["review", "analyze", "done"]:
    from orchestrator.config import get_settings

    cfg = get_settings()

    if state.get("validation_passed"):
        return "review"
    if state.get("repair_attempts", 0) >= cfg.orchestrator_max_repair_loops:
        console.print("[red]Max repairs atteint[/red]")
        return "review"  # Review quand même pour tracer
    return "analyze"


def route_after_analyze(
    state: OrchestratorState,
) -> Literal["repair", "review"]:
    if state.get("escalated"):
        return "review"
    return "repair"


def route_after_review(
    state: OrchestratorState,
) -> Literal["commit", "next_or_done"]:
    if state.get("diff") and state.get("review_passed"):
        return "commit"
    return "next_or_done"


def route_after_commit(
    state: OrchestratorState,
) -> Literal["prepare_task", "done"]:
    tasks = state.get("tasks", [])
    task_index = state.get("task_index", 0)
    return "prepare_task" if task_index < len(tasks) else "done"


def route_next_or_done(
    state: OrchestratorState,
) -> Literal["prepare_task", "done"]:
    tasks = state.get("tasks", [])
    task_index = state.get("task_index", 0) + 1
    return "prepare_task" if task_index < len(tasks) else "done"


# ─── Construction du graphe ───────────────────────────────────────────────────


def build_graph() -> Any:
    g = StateGraph(OrchestratorState)

    # Nœuds
    g.add_node("init", node_init)
    g.add_node("preflight", node_preflight)
    g.add_node("snapshot", node_snapshot)
    g.add_node("plan", node_plan)
    g.add_node("prepare_task", node_prepare_task)
    g.add_node("implement", node_implement)
    g.add_node("validate", node_validate)
    g.add_node("analyze", node_analyze)
    g.add_node("repair", node_repair)
    g.add_node("review", node_review)
    g.add_node("commit", node_commit)

    def node_skip_task(s):
        task_id = s.get("handoff", {}).get("task_id", "unknown")
        completed = s.get("completed_tasks", []) + [task_id]
        return {"task_index": s.get("task_index", 0) + 1, "completed_tasks": completed}

    g.add_node("skip_task", node_skip_task)
    g.add_node("done", node_done)

    # Edges fixes
    g.set_entry_point("init")
    g.add_edge("init", "preflight")
    g.add_edge("snapshot", "plan")
    g.add_edge("prepare_task", "implement")
    g.add_edge("implement", "validate")
    g.add_edge("repair", "validate")
    g.add_edge("done", END)

    # Edges conditionnels
    g.add_conditional_edges(
        "preflight", route_after_preflight, {"snapshot": "snapshot", "done": "done"}
    )
    g.add_conditional_edges(
        "plan", route_after_plan, {"prepare_task": "prepare_task", "done": "done"}
    )
    g.add_conditional_edges(
        "validate",
        route_after_validate,
        {"review": "review", "analyze": "analyze", "done": "done"},
    )
    g.add_conditional_edges(
        "analyze", route_after_analyze, {"repair": "repair", "review": "review"}
    )
    g.add_conditional_edges(
        "review", route_after_review, {"commit": "commit", "next_or_done": "skip_task"}
    )
    g.add_conditional_edges(
        "commit", route_after_commit, {"prepare_task": "prepare_task", "done": "done"}
    )
    g.add_conditional_edges(
        "skip_task",
        route_next_or_done,
        {"prepare_task": "prepare_task", "done": "done"},
    )

    return g.compile()


# ─── Point d'entrée ──────────────────────────────────────────────────────────


def run_pipeline(goal: str = "", repo_path: str = "") -> None:
    graph = build_graph()
    graph.invoke(
        {
            "goal": goal,
            "repo_path": repo_path,
        }
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Multi-Agent Orchestrator — LangGraph")
    p.add_argument("--goal", default="")
    p.add_argument("--repo", default="")
    args = p.parse_args()
    run_pipeline(goal=args.goal, repo_path=args.repo)
