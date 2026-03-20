"""
orchestrator/workers/codex_worker.py
Worker Codex CLI : implémentation et repair ciblé par fichier.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from orchestrator.config import get_settings

cfg = get_settings()
CODEX_BIN = "/home/gloaguen/.npm-global/bin/codex"


def _rtk(text: str) -> str:
    """Compresse via RTK si disponible, sinon pass-through."""
    if not cfg.rtk_available:
        return text
    try:
        r = subprocess.run(
            ["rtk", "compress"], input=text, capture_output=True, text=True, timeout=15
        )
        return r.stdout if r.returncode == 0 and r.stdout else text
    except Exception:
        return text


def _run_codex(prompt: str, repo_path: str) -> tuple[int, str, str]:
    """Lance codex exec en mode non-interactif."""
    env = {**os.environ, "OPENAI_API_KEY": cfg.openai_api_key}
    try:
        result = subprocess.run(
            [CODEX_BIN, "exec", "--dangerously-bypass-approvals-and-sandbox", prompt],
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=cfg.orchestrator_task_timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout après {cfg.orchestrator_task_timeout}s"
    except FileNotFoundError:
        return 1, "", f"codex non trouvé : {CODEX_BIN}"


def _count_errors(ruff_out: str, mypy_out: str, test_out: str) -> int:
    """Compte le nombre total d'erreurs pour détecter les régressions."""
    count = 0
    # Ruff : une erreur par ligne non vide
    count += sum(1 for line in ruff_out.strip().splitlines() if line.strip())
    # Mypy : lignes contenant "error:"
    count += sum(1 for line in mypy_out.splitlines() if "error:" in line)
    # Pytest : extraire le nombre d'échecs
    for line in test_out.splitlines():
        if "failed" in line:
            try:
                count += int(line.strip().split()[0])
            except (ValueError, IndexError):
                count += 1
            break
    return count


def implement_task(handoff: dict, repo_path: str) -> dict[str, Any]:
    """Implémente une tâche à partir d'un handoff."""
    prompt = _rtk(f"""Implémente la tâche suivante dans le repo.

TÂCHE : {handoff.get("task_title", "")}
OBJECTIF : {handoff.get("task_objective", "")}

FICHIERS AUTORISÉS (ne toucher QUE ceux-là) :
{chr(10).join("- " + f for f in handoff.get("files_allowed", []))}

CRITÈRES D'ACCEPTATION :
{chr(10).join("- " + c for c in handoff.get("acceptance_criteria", []))}

RÈGLES ABSOLUES :
- Python 3.11+, annotations de type obligatoires
- Pas de secrets en dur
- Ne modifier AUCUN fichier hors de la liste ci-dessus
- Si impossible dans le scope, expliquer et arrêter
""")

    rc, stdout, stderr = _run_codex(prompt, repo_path)

    diff = subprocess.run(
        ["git", "diff"], cwd=repo_path, capture_output=True, text=True
    ).stdout

    return {
        "success": rc == 0,
        "diff": diff,
        "stdout": stdout[:500],
        "error": stderr[:300] if rc != 0 else "",
    }


def repair_task(
    handoff: dict,
    repo_path: str,
    ruff_out: str,
    mypy_out: str,
    test_out: str,
    attempt: int,
    analysis: dict | None = None,
) -> dict[str, Any]:
    """
    Repair ciblé guidé par l'analyse Claude.

    Si analysis est fourni (depuis claude_worker.analyze_failure) :
    - Codex reçoit des instructions précises par fichier
    - Reset automatique si le repair empire la situation
    """
    # Compter les erreurs AVANT repair pour détecter les régressions
    errors_before = _count_errors(ruff_out, mypy_out, test_out)

    # Récupérer le diff actuel
    diff = subprocess.run(
        ["git", "diff"], cwd=repo_path, capture_output=True, text=True
    ).stdout

    # Construire le prompt repair selon qu'on a une analyse ou non
    if analysis and analysis.get("repair_hints"):
        # Mode guidé par Claude — instructions précises
        files_to_fix = analysis.get("files_to_fix", handoff.get("files_allowed", []))
        hints = "\n".join(f"- {h}" for h in analysis["repair_hints"])

        prompt = _rtk(f"""Repair loop {attempt} — Corriger uniquement les erreurs suivantes.

CAUSE PRINCIPALE : {analysis.get("root_cause", "voir erreurs ci-dessous")}

FICHIERS À CORRIGER (UNIQUEMENT ceux-là) :
{chr(10).join("- " + f for f in files_to_fix)}

INSTRUCTIONS PRÉCISES :
{hints}

ERREURS RUFF :
{ruff_out[:400]}

ERREURS MYPY :
{mypy_out[:400]}

ERREURS TESTS :
{test_out[:300]}

RÈGLES :
- Corriger UNIQUEMENT les erreurs listées
- Ne pas modifier le comportement fonctionnel
- Ne pas toucher aux fichiers hors de la liste ci-dessus
- Si une erreur est dans un fichier hors scope, l'ignorer et le signaler
""")
    else:
        # Mode générique (fallback sans analyse Claude)
        prompt = _rtk(f"""Repair loop {attempt} — Corriger les erreurs de validation.

FICHIERS AUTORISÉS : {handoff.get("files_allowed", [])}

ERREURS RUFF :
{ruff_out[:500]}

ERREURS MYPY :
{mypy_out[:500]}

ERREURS TESTS :
{test_out[:400]}

DIFF ACTUEL :
{diff[:1500]}

Ne pas modifier le comportement fonctionnel. Ne pas dépasser le scope.
""")

    rc, _, stderr = _run_codex(prompt, repo_path)

    # Vérifier si le repair a empiré la situation (régression)
    subprocess.run(
        "ruff check . --output-format=concise",
        shell=True,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    # Recalculer les erreurs après repair
    new_ruff_out = subprocess.run(
        "ruff check . --output-format=concise",
        shell=True,
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout
    new_mypy_out = subprocess.run(
        "mypy . --ignore-missing-imports",
        shell=True,
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout
    new_test_out = subprocess.run(
        "pytest -q --tb=short 2>&1 | tail -10",
        shell=True,
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout

    errors_after = _count_errors(new_ruff_out, new_mypy_out, new_test_out)

    # Reset si régression détectée
    regressed = errors_after > errors_before
    if regressed:
        files_to_reset = handoff.get("files_allowed", [])
        if files_to_reset:
            reset_cmd = f"git checkout -- {' '.join(files_to_reset)}"
            subprocess.run(reset_cmd, shell=True, cwd=repo_path)

    diff2 = subprocess.run(
        ["git", "diff"], cwd=repo_path, capture_output=True, text=True
    ).stdout

    return {
        "success": rc == 0 and not regressed,
        "diff": diff2,
        "error": stderr[:300] if rc != 0 else "",
        "regressed": regressed,
        "errors_before": errors_before,
        "errors_after": errors_after,
    }
