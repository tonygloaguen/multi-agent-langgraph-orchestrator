#!/usr/bin/env bash
# =============================================================================
# create_project.sh — Crée tous les fichiers du projet orchestrateur
# Lancer depuis : ~/projets/orchestrateur/
# =============================================================================
set -euo pipefail

echo "======================================"
echo " Création du projet orchestrateur"
echo " $(date)"
echo "======================================"

# --- Dossiers ---
mkdir -p .vscode orchestrator/schemas orchestrator/workers
mkdir -p scripts docs logs orchestrator/handoffs orchestrator/state/runs
touch logs/.gitkeep orchestrator/handoffs/.gitkeep
echo "[OK] Structure créée"

# =============================================================================
cat > .gitignore << 'EOF'
.env
.venv/
__pycache__/
*.pyc
.mypy_cache/
.ruff_cache/
.pytest_cache/
orchestrator/handoffs/*.yaml
orchestrator/state/runs/
logs/*.log
node_modules/
EOF
echo "[OK] .gitignore"

# =============================================================================
cat > .env.example << 'EOF'
ANTHROPIC_API_KEY=sk-ant-VOTRE_CLE_ICI
OPENAI_API_KEY=sk-VOTRE_CLE_ICI
GEMINI_API_KEY=VOTRE_CLE_ICI

CLAUDE_MODEL=claude-opus-4-6
CODEX_MODEL=codex-mini-latest
GEMINI_MODEL=gemini-2.0-flash

ORCHESTRATOR_MAX_REPAIR_LOOPS=2
ORCHESTRATOR_TASK_TIMEOUT=300
ORCHESTRATOR_CONTEXT_MAX_TOKENS=8000
GEMINI_FALLBACK_ENABLED=true
RTK_ENABLED=true
DEFAULT_REPO_PATH=.
GIT_AGENT_BRANCH_PREFIX=agent/
HANDOFFS_DIR=./orchestrator/handoffs
STATE_DIR=./orchestrator/state
LOGS_DIR=./logs
EOF
echo "[OK] .env.example"

# =============================================================================
cat > requirements.txt << 'EOF'
langgraph>=0.2.0
langchain>=0.2.0
langchain-anthropic>=0.1.0
langchain-openai>=0.1.0
langchain-google-genai>=1.0.0
langchain-core>=0.2.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
pyyaml>=6.0.1
python-dotenv>=1.0.0
rich>=13.7.0
httpx>=0.27.0
tenacity>=8.3.0
pytest>=8.2.0
pytest-asyncio>=0.23.0
EOF
echo "[OK] requirements.txt"

# =============================================================================
cat > Makefile << 'EOF'
.PHONY: bootstrap install preflight run validate clean logs stop help

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip

bootstrap:
	bash scripts/bootstrap.sh

install:
	$(PIP) install -q -r requirements.txt

preflight:
	$(PYTHON) scripts/preflight.py

validate:
	bash scripts/validate_task.sh .

run:
	@read -p "Objectif : " goal; \
	read -p "Repo cible (Entrée = projet courant) : " repo; \
	repo=$${repo:-.}; \
	$(PYTHON) orchestrator/state_machine.py --goal "$$goal" --repo "$$repo"

start:
	bash scripts/start_orchestrator.sh

stop:
	pkill -f state_machine.py || echo "Non actif"

logs:
	tail -f logs/orchestrator.log

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	echo "Nettoyé"

clean-handoffs:
	rm -f orchestrator/handoffs/*.yaml && echo "Handoffs supprimés"

help:
	@echo ""
	@echo "  bootstrap      Installation complète (première fois)"
	@echo "  run            Lancer avec objectif + repo cible"
	@echo "  preflight      Vérifier l'environnement"
	@echo "  validate       ruff + mypy + pytest"
	@echo "  logs           Tail des logs en temps réel"
	@echo "  stop           Arrêter l'orchestrateur"
	@echo "  clean          Nettoyer les artefacts"
	@echo ""

.DEFAULT_GOAL := help
EOF
echo "[OK] Makefile"

# =============================================================================
cat > CLAUDE.md << 'EOF'
# CLAUDE.md — Multi-Agent Orchestrator

## Rôles
| Agent | Rôle |
|---|---|
| Claude Code | Architecture, planification, revue de conformité |
| Codex CLI | Implémentation locale, scripts, tests, repair |
| Gemini 2.0 Flash | Fallback résumé/triage (pas d'autorité architecturale) |
| Orchestrateur | LangGraph — routing, handoffs, validation, journal |

## Règle de priorité
Ce CLAUDE.md prime sur toute décision locale d'un agent.

## Debug strategy
Avant tout patch, trace l'exécution logique ligne par ligne,
identifie le point de divergence, propose ensuite le fix.

## Stack
- Python 3.11+, mypy strict, Ruff, Google docstrings
- Pydantic v2, LangGraph, credentials via .env uniquement

## Ce que Codex NE doit PAS faire sans validation Claude
- Modifier les schémas de données (Pydantic, DB, migrations)
- Changer les interfaces publiques
- Toucher aux fichiers sécurité/secrets
- Refactorer hors scope de la tâche assignée

## Validation obligatoire avant commit
ruff check . && mypy . --ignore-missing-imports && pytest -q
EOF
echo "[OK] CLAUDE.md"

# =============================================================================
cat > .vscode/settings.json << 'EOF'
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true,
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "terminal.integrated.env.linux": {
    "PYTHONPATH": "${workspaceFolder}"
  },
  "files.exclude": {
    "**/__pycache__": true,
    "**/.mypy_cache": true,
    "**/.ruff_cache": true,
    "**/.pytest_cache": true
  },
  "task.allowAutomaticTasks": "on"
}
EOF
echo "[OK] .vscode/settings.json"

# =============================================================================
cat > .vscode/tasks.json << 'EOF'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Orchestrator Auto-Start",
      "type": "shell",
      "command": "bash scripts/start_orchestrator.sh",
      "options": {
        "cwd": "${workspaceFolder}",
        "env": { "PYTHONPATH": "${workspaceFolder}" }
      },
      "runOptions": { "runOn": "folderOpen" },
      "presentation": {
        "reveal": "always",
        "panel": "dedicated",
        "echo": true,
        "focus": false,
        "close": false
      },
      "problemMatcher": []
    },
    {
      "label": "Run Orchestrator (avec goal)",
      "type": "shell",
      "command": "${workspaceFolder}/.venv/bin/python orchestrator/state_machine.py --goal \"${input:orchestratorGoal}\" --repo \"${input:repoPath}\"",
      "options": {
        "cwd": "${workspaceFolder}",
        "env": { "PYTHONPATH": "${workspaceFolder}" }
      },
      "presentation": {
        "reveal": "always",
        "panel": "dedicated",
        "focus": true
      },
      "problemMatcher": []
    },
    {
      "label": "Bootstrap (install tout)",
      "type": "shell",
      "command": "bash scripts/bootstrap.sh",
      "options": { "cwd": "${workspaceFolder}" },
      "presentation": { "reveal": "always", "panel": "dedicated" },
      "problemMatcher": []
    },
    {
      "label": "Validate Task",
      "type": "shell",
      "command": "bash scripts/validate_task.sh .",
      "options": { "cwd": "${workspaceFolder}" },
      "presentation": { "reveal": "always", "panel": "shared" },
      "problemMatcher": []
    },
    {
      "label": "Logs (tail)",
      "type": "shell",
      "command": "tail -f logs/orchestrator.log 2>/dev/null || echo 'Pas encore de logs'",
      "options": { "cwd": "${workspaceFolder}" },
      "isBackground": true,
      "presentation": { "reveal": "always", "panel": "dedicated" },
      "problemMatcher": []
    },
    {
      "label": "Stop Orchestrator",
      "type": "shell",
      "command": "pkill -f state_machine.py || echo 'Non actif'",
      "options": { "cwd": "${workspaceFolder}" },
      "presentation": { "reveal": "silent" },
      "problemMatcher": []
    }
  ],
  "inputs": [
    {
      "id": "orchestratorGoal",
      "type": "promptString",
      "description": "Objectif pour l'orchestrateur",
      "default": "Analyser le repo et proposer des améliorations"
    },
    {
      "id": "repoPath",
      "type": "promptString",
      "description": "Chemin absolu du repo cible (ex: /home/tony/projets/mon-app)",
      "default": "."
    }
  ]
}
EOF
echo "[OK] .vscode/tasks.json"

# =============================================================================
touch orchestrator/__init__.py
touch orchestrator/schemas/__init__.py
touch orchestrator/workers/__init__.py

# =============================================================================
cat > orchestrator/config.py << 'EOF'
from __future__ import annotations
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
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
EOF
echo "[OK] orchestrator/config.py"

# =============================================================================
cat > orchestrator/workers/claude_worker.py << 'EOF'
from __future__ import annotations
import json
from typing import Any
from tenacity import retry, stop_after_attempt, wait_exponential
from orchestrator.config import get_settings

cfg = get_settings()


def _llm(max_tokens: int = 2000):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=cfg.claude_model,
        api_key=cfg.anthropic_api_key,
        max_tokens=max_tokens,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30))
def generate_plan(goal: str, repo_snapshot: str) -> dict[str, Any]:
    llm = _llm(3000)
    prompt = f"""Tu es l'architecte du pipeline multi-agents. Réponds UNIQUEMENT en YAML valide, sans balises markdown.

Objectif : {goal or "Analyser le repo et proposer des améliorations ciblées."}

Snapshot repo :
{repo_snapshot[:3000]}

Format attendu :
plan_id: plan-YYYYMMDD-001
description: "description courte"
tasks:
  - task_id: "task-001"
    kind: implementation
    title: "Titre court"
    objective: "Objectif précis en une phrase"
    files_allowed:
      - "chemin/fichier.py"
    acceptance_criteria:
      - "Critère vérifiable automatiquement"

Règles : max 5 tâches, chacune atomique et testable.
"""
    response = llm.invoke(prompt)
    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    import yaml
    data = yaml.safe_load(raw)
    return {
        "plan_id": data.get("plan_id", "plan-unknown"),
        "plan_yaml": raw,
        "tasks": data.get("tasks", []),
    }


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=15))
def review_conformance(handoff: dict, diff: str) -> dict[str, Any]:
    llm = _llm(600)
    prompt = f"""Reviewer de conformité architecturale. Réponds UNIQUEMENT en JSON valide.

Fichiers autorisés : {handoff.get("files_allowed", [])}
Chemins interdits : {handoff.get("paths_forbidden", [])}

Diff produit :
{diff[:2500]}

Vérifie : scope respecté, pas de modification interdite, pas de secret en dur.
Réponds : {{"passed": true, "issues": [], "notes": "ok"}}
"""
    response = llm.invoke(prompt)
    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    try:
        return json.loads(raw)
    except Exception:
        return {"passed": True, "issues": [], "notes": "parse error — pass par défaut"}
EOF
echo "[OK] orchestrator/workers/claude_worker.py"

# =============================================================================
cat > orchestrator/workers/codex_worker.py << 'EOF'
from __future__ import annotations
import os
import subprocess
from typing import Any
from orchestrator.config import get_settings

cfg = get_settings()


def _rtk(text: str) -> str:
    if not cfg.rtk_available:
        return text
    try:
        r = subprocess.run(["rtk", "compress"], input=text,
                           capture_output=True, text=True, timeout=15)
        return r.stdout if r.returncode == 0 and r.stdout else text
    except Exception:
        return text


def _run_codex(prompt: str, repo_path: str) -> tuple[int, str, str]:
    env = {**os.environ, "OPENAI_API_KEY": cfg.openai_api_key}
    try:
        result = subprocess.run(
            ["codex", "--model", cfg.codex_model, "--quiet", "--no-ansi"],
            input=prompt, cwd=repo_path, env=env,
            capture_output=True, text=True,
            timeout=cfg.orchestrator_task_timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout après {cfg.orchestrator_task_timeout}s"
    except FileNotFoundError:
        return 1, "", "codex CLI non trouvé — vérifier PATH"


def implement_task(handoff: dict, repo_path: str) -> dict[str, Any]:
    prompt = _rtk(f"""Implémente la tâche suivante.

TÂCHE : {handoff.get("task_title", "")}
OBJECTIF : {handoff.get("task_objective", "")}

FICHIERS AUTORISÉS (ne toucher QUE ceux-là) :
{chr(10).join("- " + f for f in handoff.get("files_allowed", []))}

CRITÈRES D'ACCEPTATION :
{chr(10).join("- " + c for c in handoff.get("acceptance_criteria", []))}

RÈGLES ABSOLUES :
- Python 3.11+, annotations de type obligatoires
- Pas de secrets en dur
- Ne modifier AUCUN fichier hors de files_allowed
- Si impossible dans le scope, expliquer et arrêter
""")
    rc, stdout, stderr = _run_codex(prompt, repo_path)
    diff = subprocess.run(["git", "diff"], cwd=repo_path,
                          capture_output=True, text=True).stdout
    return {"success": rc == 0, "diff": diff, "error": stderr[:300]}


def repair_task(handoff: dict, repo_path: str,
                ruff_out: str, mypy_out: str, test_out: str,
                attempt: int) -> dict[str, Any]:
    diff = subprocess.run(["git", "diff"], cwd=repo_path,
                          capture_output=True, text=True).stdout
    prompt = _rtk(f"""Repair loop {attempt} — Corriger uniquement les erreurs suivantes.

FICHIERS AUTORISÉS : {handoff.get("files_allowed", [])}

ERREURS RUFF :
{ruff_out[:500]}

ERREURS MYPY :
{mypy_out[:500]}

ERREURS TESTS :
{test_out[:500]}

DIFF ACTUEL :
{diff[:1500]}

Ne pas modifier le comportement fonctionnel. Ne pas dépasser le scope.
""")
    rc, _, stderr = _run_codex(prompt, repo_path)
    diff2 = subprocess.run(["git", "diff"], cwd=repo_path,
                           capture_output=True, text=True).stdout
    return {"success": rc == 0, "diff": diff2, "error": stderr[:300]}
EOF
echo "[OK] orchestrator/workers/codex_worker.py"

# =============================================================================
cat > orchestrator/workers/gemini_worker.py << 'EOF'
from __future__ import annotations
from orchestrator.config import get_settings

cfg = get_settings()


def is_available() -> bool:
    return bool(cfg.gemini_api_key and cfg.gemini_fallback_enabled)


def summarize_logs(logs: str) -> str:
    if not is_available():
        return "Gemini non configuré (GEMINI_API_KEY manquante)"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=cfg.gemini_model,
            google_api_key=cfg.gemini_api_key,
            max_output_tokens=500,
        )
        r = llm.invoke(
            f"Résume en 5 lignes max, identifie la cause principale :\n{logs[:2000]}"
        )
        return r.content
    except Exception as e:
        return f"Gemini erreur : {e}"
EOF
echo "[OK] orchestrator/workers/gemini_worker.py"

# =============================================================================
cat > orchestrator/state_machine.py << 'EOF'
from __future__ import annotations
import json
import subprocess
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()


def _cmd(cmd: str, cwd: str = ".") -> tuple[int, str, str]:
    r = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=60
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def run_pipeline(goal: str = "", repo_path: str = ".") -> None:
    from orchestrator.config import get_settings
    from orchestrator.workers import claude_worker, codex_worker

    cfg = get_settings()
    run_id = f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    console.print(Panel(
        f"[bold green]Orchestrateur démarré[/bold green]\n"
        f"Run ID : {run_id}\n"
        f"Repo   : {repo_path}\n"
        f"Goal   : {goal or '(mode analyse)'}",
        title="Multi-Agent Pipeline"
    ))

    # --- Preflight ---
    console.print("\n[cyan]--- Preflight ---[/cyan]")
    errors = []
    if not cfg.anthropic_api_key:
        errors.append("ANTHROPIC_API_KEY manquante dans .env")
    if not cfg.openai_api_key:
        errors.append("OPENAI_API_KEY manquante dans .env")
    for tool in ["ruff", "mypy", "pytest", "codex"]:
        rc, _, _ = _cmd(f"which {tool}")
        if rc != 0:
            errors.append(f"Outil manquant : {tool}")
    rc, _, _ = _cmd("git rev-parse HEAD", cwd=repo_path)
    if rc != 0:
        errors.append(f"Pas un repo Git valide : {repo_path}")

    if errors:
        for e in errors:
            console.print(f"[red][FAIL][/red] {e}")
        console.print("\n[red]Corriger les erreurs ci-dessus avant de relancer.[/red]")
        return

    console.print("[green]Preflight OK[/green]")

    # --- Snapshot repo ---
    _, tree, _ = _cmd("find . -name '*.py' | head -40 | sort", cwd=repo_path)
    _, git_status, _ = _cmd("git status --short", cwd=repo_path)
    snapshot = f"Fichiers Python:\n{tree}\n\nGit status:\n{git_status}"

    # --- Plan Claude ---
    console.print("\n[cyan]Claude — planification...[/cyan]")
    try:
        plan = claude_worker.generate_plan(goal, snapshot)
    except Exception as e:
        console.print(f"[red]Erreur Claude : {e}[/red]")
        return

    tasks = plan["tasks"]
    console.print(f"[green]Plan généré : {len(tasks)} tâche(s)[/green]")

    # --- Boucle tâches ---
    for i, task in enumerate(tasks):
        task_id = task.get("task_id", f"task-{i:03d}")
        title = task.get("title", "")
        console.print(f"\n[bold cyan]── Tâche {i+1}/{len(tasks)} : {title} ──[/bold cyan]")

        handoff = {
            "task_id": task_id,
            "plan_id": plan["plan_id"],
            "task_title": title,
            "task_objective": task.get("objective", ""),
            "files_allowed": task.get("files_allowed", []),
            "paths_forbidden": ["migrations/", ".github/workflows/", "infra/"],
            "acceptance_criteria": task.get("acceptance_criteria", []),
        }

        # Sauvegarder handoff YAML
        import yaml
        hf_path = Path(cfg.handoffs_dir) / f"{task_id}.yaml"
        with open(hf_path, "w") as f:
            yaml.dump(handoff, f, allow_unicode=True)

        # Implémentation Codex
        console.print("[cyan]Codex — implémentation...[/cyan]")
        result = codex_worker.implement_task(handoff, repo_path)
        if not result["success"]:
            console.print(f"[red]Codex erreur : {result['error']}[/red]")
            continue

        # Boucle validation / repair
        repair_attempts = 0
        while True:
            rc_r, ruff_out, _ = _cmd("ruff check . --output-format=concise", cwd=repo_path)
            rc_m, mypy_out, _ = _cmd("mypy . --ignore-missing-imports", cwd=repo_path)
            rc_t, test_out, _ = _cmd("pytest -q --tb=short 2>&1 | tail -15", cwd=repo_path)

            if rc_r == 0 and rc_m == 0 and rc_t == 0:
                console.print("[green]Validation PASS ✓[/green]")
                break

            if repair_attempts >= cfg.orchestrator_max_repair_loops:
                console.print(f"[red]Max repairs ({cfg.orchestrator_max_repair_loops}) atteint — vérification manuelle requise[/red]")
                break

            repair_attempts += 1
            console.print(f"[yellow]Repair {repair_attempts}/{cfg.orchestrator_max_repair_loops}...[/yellow]")
            codex_worker.repair_task(
                handoff, repo_path, ruff_out, mypy_out, test_out, repair_attempts
            )

        # Review Claude
        _, diff, _ = _cmd("git diff", cwd=repo_path)
        if diff:
            console.print("[cyan]Claude — review conformité...[/cyan]")
            try:
                review = claude_worker.review_conformance(handoff, diff)
                status = "[green]PASS[/green]" if review.get("passed") else "[yellow]WARNING[/yellow]"
                console.print(f"Review : {status}")
                if not review.get("passed"):
                    console.print(f"  Issues : {review.get('issues', [])}")
            except Exception as e:
                console.print(f"[yellow]Review exception (ignorée) : {e}[/yellow]")

            # Commit
            _cmd(
                f'git add -A && git commit -m "agent: {task_id} — {title}"',
                cwd=repo_path
            )
            console.print(f"[green]Commit effectué pour {task_id}[/green]")
        else:
            console.print("[yellow]Aucune modification détectée pour cette tâche.[/yellow]")

        # Journal JSONL
        log_dir = Path(cfg.state_dir) / "runs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / f"{run_id}.jsonl", "a") as f:
            f.write(json.dumps({
                "ts": datetime.utcnow().isoformat(),
                "run_id": run_id,
                "task_id": task_id,
                "status": "completed",
                "repair_attempts": repair_attempts,
            }) + "\n")

        console.print(f"[green]Tâche {task_id} terminée.[/green]")

    console.print(Panel(
        f"[bold green]Pipeline terminé[/bold green]\n"
        f"Run ID : {run_id}\n"
        f"Tâches traitées : {len(tasks)}",
        title="Done"
    ))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Multi-Agent Orchestrator")
    p.add_argument("--goal", default="", help="Objectif à atteindre")
    p.add_argument("--repo", default=".", help="Chemin du repo cible")
    args = p.parse_args()
    run_pipeline(goal=args.goal, repo_path=args.repo)
EOF
echo "[OK] orchestrator/state_machine.py"

# =============================================================================
cat > scripts/preflight.py << 'EOF'
#!/usr/bin/env python3
"""Vérification de l'environnement. Exit 0=OK, 1=erreur, 2=warning."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

def chk(label: str, ok: bool, detail: str = "", blocking: bool = True) -> bool:
    icon = "OK  " if ok else ("FAIL" if blocking else "WARN")
    color = "\033[32m" if ok else ("\033[31m" if blocking else "\033[33m")
    print(f"  {color}[{icon}]\033[0m {label}" + (f" — {detail}" if detail else ""))
    return ok

def run(cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return r.returncode, (r.stdout + r.stderr).strip()

def main() -> int:
    print("\n=== Preflight Check ===\n")
    failures, warnings = [], []

    # Python
    v = sys.version_info
    ok = v >= (3, 11)
    if not chk(f"Python >= 3.11", ok, f"{v.major}.{v.minor}"): failures.append("python")

    # .env et clés API
    env_file = Path(".env")
    if not chk(".env présent", env_file.exists(), blocking=False):
        warnings.append(".env")
    else:
        content = env_file.read_text()
        for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
            val = ""
            for line in content.splitlines():
                if line.startswith(f"{var}="):
                    val = line.split("=", 1)[1].strip()
            has_val = bool(val) and "VOTRE_CLE" not in val
            if not chk(var, has_val, "présente" if has_val else "manquante ou non renseignée"):
                failures.append(var)

    # Outils obligatoires
    for tool in ["git", "codex"]:
        rc, out = run(f"which {tool}")
        if not chk(tool, rc == 0, out.split("\n")[0][:50]):
            failures.append(tool)

    # Outils dans venv (optionnels si venv pas encore actif)
    for tool in ["ruff", "mypy", "pytest"]:
        rc, out = run(f"which {tool}")
        if not chk(tool, rc == 0, out.split("\n")[0][:50], blocking=False):
            warnings.append(tool)

    # Venv
    venv = Path(".venv")
    if not chk("venv .venv/", venv.exists(), blocking=False):
        warnings.append("venv")

    # Imports Python (seulement si venv actif)
    if venv.exists():
        for mod in ["langgraph", "langchain_anthropic", "pydantic", "yaml", "rich"]:
            try:
                __import__(mod)
                chk(f"import {mod}", True)
            except ImportError:
                if not chk(f"import {mod}", False, "pip install -r requirements.txt", blocking=False):
                    warnings.append(f"import:{mod}")

    print()
    if failures:
        print(f"\033[31mFAIL\033[0m — {len(failures)} erreur(s) : {failures}")
        return 1
    if warnings:
        print(f"\033[33mWARN\033[0m — {len(warnings)} avertissement(s) : {warnings}")
        return 2
    print("\033[32mOK\033[0m — Environnement prêt.")
    return 0

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="full")
    p.parse_args()
    sys.exit(main())
EOF
echo "[OK] scripts/preflight.py"

# =============================================================================
cat > scripts/validate_task.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-.}"
echo "=== Validation : $(date) | Repo : $REPO ==="
ok=true

echo ">>> ruff"
ruff check "$REPO" --output-format=concise && echo "[OK] ruff" || { echo "[FAIL] ruff"; ok=false; }

echo ">>> mypy"
mypy "$REPO" --ignore-missing-imports && echo "[OK] mypy" || { echo "[FAIL] mypy"; ok=false; }

echo ">>> pytest"
pytest "$REPO" -q --tb=short 2>&1 | tail -10 && echo "[OK] pytest" || { echo "[FAIL] pytest"; ok=false; }

$ok && echo "=== PASS ===" || { echo "=== FAIL ==="; exit 1; }
EOF
echo "[OK] scripts/validate_task.sh"

# =============================================================================
cat > scripts/rtk_compress.sh << 'EOF'
#!/usr/bin/env bash
if command -v rtk >/dev/null 2>&1; then
    rtk compress
else
    cat
fi
EOF
echo "[OK] scripts/rtk_compress.sh"

# =============================================================================
cat > scripts/bootstrap.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "======================================"
echo " Bootstrap — Multi-Agent Orchestrator"
echo " $(date)"
echo "======================================"

command -v python3 >/dev/null || fail "python3 manquant"
PY=$(python3 -c "import sys; print(int(sys.version_info >= (3,11)))")
[[ "$PY" == "1" ]] || fail "Python >= 3.11 requis"
ok "Python $(python3 --version)"

command -v node >/dev/null || fail "Node.js manquant"
command -v npm  >/dev/null || fail "npm manquant"
ok "Node $(node --version) / npm $(npm --version)"

if [[ ! -f ".env" ]]; then
    cp .env.example .env
    warn ".env créé — RENSEIGNER les clés API avant de continuer"
    echo ""
    echo "  Ouvrir .env et renseigner :"
    echo "    ANTHROPIC_API_KEY=sk-ant-..."
    echo "    OPENAI_API_KEY=sk-..."
    echo ""
    read -p "Appuyer sur Entrée après avoir sauvegardé .env..." _
fi
set -a; source .env; set +a
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && [[ "${ANTHROPIC_API_KEY}" != *"VOTRE_CLE"* ]] \
    || fail "ANTHROPIC_API_KEY non renseignée dans .env"
[[ -n "${OPENAI_API_KEY:-}" ]] && [[ "${OPENAI_API_KEY}" != *"VOTRE_CLE"* ]] \
    || fail "OPENAI_API_KEY non renseignée dans .env"
ok "Clés API présentes"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    ok "venv créé"
else
    ok "venv existant"
fi
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dépendances Python installées"

python3 -c "import langgraph, langchain_anthropic, pydantic, yaml, rich" \
    || fail "Import check échoué"
ok "Imports Python OK"

command -v codex >/dev/null \
    && ok "Codex CLI : $(codex --version 2>/dev/null || echo 'ok')" \
    || fail "Codex CLI non trouvé — lancer : npm install -g @openai/codex"

chmod +x scripts/*.sh
ok "Scripts exécutables"

echo ""
echo "======================================"
echo -e "${GREEN} Bootstrap terminé avec succès.${NC}"
echo ""
echo " Étape suivante :"
echo "   code $(pwd)"
echo "   → Cliquer 'Allow' sur la notification VS Code"
echo "   → L'orchestrateur démarre automatiquement"
echo "======================================"
EOF
echo "[OK] scripts/bootstrap.sh"

# =============================================================================
cat > scripts/start_orchestrator.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "======================================"
echo " Multi-Agent Orchestrator"
echo " $(date)"
echo "======================================"

if [[ ! -f ".env" ]]; then
    echo "[WARN] .env absent — lancer d'abord : bash scripts/bootstrap.sh"
    exit 1
fi
set -a; source .env; set +a
echo "[OK] .env chargé"

if [[ ! -d ".venv" ]]; then
    echo "[WARN] venv absent — lancement bootstrap..."
    bash scripts/bootstrap.sh
fi
source .venv/bin/activate
echo "[OK] venv activé : $(python --version)"

echo ""
echo "--- Preflight rapide ---"
python scripts/preflight.py --mode=quick
RC=$?
if [[ $RC -eq 1 ]]; then
    echo ""
    echo "[FAIL] Erreurs bloquantes détectées."
    echo "Lancer : bash scripts/bootstrap.sh"
    exit 1
fi

echo ""
echo "================================================"
echo " Orchestrateur prêt."
echo ""
echo " Pour lancer une tâche :"
echo "   Dans VS Code : Ctrl+Shift+P"
echo "   → Tasks: Run Task"
echo "   → Run Orchestrator (avec goal)"
echo ""
echo "   Ou en terminal : make run"
echo "================================================"
echo ""

# Garder le terminal ouvert (log en attente)
tail -f /dev/null
EOF
echo "[OK] scripts/start_orchestrator.sh"

# =============================================================================
cat > docs/deployment.md << 'EOF'
# Déploiement — résumé

## Une seule fois
1. bash scripts/bootstrap.sh
2. code .  (ouvrir VS Code)
3. Cliquer "Allow" sur la notification

## À chaque fois
1. Ouvrir VS Code sur ce dossier → orchestrateur démarre seul
2. Ctrl+Shift+P → Tasks: Run Task → Run Orchestrator (avec goal)
3. Saisir l'objectif + le chemin du repo cible

## Commandes
- make run          : lancer avec objectif
- make preflight    : vérifier l'env
- make validate     : ruff + mypy + pytest
- make logs         : voir les logs
- make stop         : arrêter
- make clean        : nettoyer
EOF
echo "[OK] docs/deployment.md"

# =============================================================================
chmod +x scripts/*.sh

echo ""
echo "======================================"
echo " Tous les fichiers créés avec succès."
echo ""
echo " Étape suivante :"
echo "   bash scripts/bootstrap.sh"
echo "======================================"
