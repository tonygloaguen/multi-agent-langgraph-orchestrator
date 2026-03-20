"""
orchestrator/workers/claude_worker.py
Worker planification/review via Claude Code CLI (subprocess).
Utilise le plan Pro + crédits API Anthropic.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from orchestrator.workers.llm_provider import (
    LLMInvocationError,
    ProviderConfig,
    ProviderStatus,
    call_llm,
)

CLAUDE_BIN = "/home/gloaguen/.local/bin/claude"
TIMEOUT = 120

_CLAUDE_CONFIG = ProviderConfig(name="claude", bin_path=CLAUDE_BIN, timeout=TIMEOUT)


def _call_claude(prompt: str) -> str:
    """Appelle Claude Code CLI en mode non-interactif.

    Capture stdout ET stderr pour la détection de rate limit.
    Lève LLMInvocationError (sous-classe RuntimeError) si rate-limited.
    Lève RuntimeError pour les autres erreurs.
    """
    result = call_llm(_CLAUDE_CONFIG, prompt)

    if result.is_ok:
        return result.output

    # Rate limit → erreur typée pour le fallback
    if result.status == ProviderStatus.RATE_LIMITED:
        raise LLMInvocationError(result)

    # Autres erreurs → RuntimeError compatible avec le code existant
    combined = (result.stdout + "\n" + result.stderr).strip()
    raise RuntimeError(
        f"Claude Code erreur (rc={result.rc}) : {combined[:500]}"
    )


def _clean_markdown(raw: str) -> str:
    """Supprime les balises markdown (```yaml, ```json, ```python, ```)."""
    if "```" not in raw:
        return raw.strip()
    lines = raw.split("\n")
    cleaned, in_block = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        # Garder le contenu DANS le bloc (c est le contenu utile)
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _extract_json(raw: str) -> dict:
    """Extrait robustement un objet JSON depuis une réponse."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"Aucun JSON valide trouvé dans : {raw[:300]}")


def generate_plan(goal: str, repo_snapshot: str) -> dict[str, Any]:
    """
    Génère un plan structuré YAML depuis un objectif utilisateur.
    Retourne : {"plan_id": str, "plan_yaml": str, "tasks": list}
    """
    import yaml

    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    prompt = f"""Tu es l'architecte d'un pipeline multi-agents. Réponds UNIQUEMENT en YAML valide, sans balises markdown, sans explication.

Objectif : {goal or "Analyser le repo et proposer des améliorations ciblées."}

Snapshot repo :
{repo_snapshot[:3000]}

Format YAML attendu :
plan_id: plan-{today}-001
description: "description courte"
tasks:
  - task_id: "task-001"
    kind: implementation
    title: "Titre court"
    objective: "Objectif précis en une phrase"
    files_allowed:
      - "chemin/relatif/fichier.py"
    acceptance_criteria:
      - "Critère vérifiable automatiquement"

Règles : max 3 tâches, atomiques, fichiers existants dans le repo. YAML uniquement.
"""

    raw = _clean_markdown(_call_claude(prompt))

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise RuntimeError(f"YAML invalide : {e}\n\nRaw:\n{raw[:500]}")

    if not isinstance(data, dict) or "tasks" not in data:
        raise RuntimeError(f"Structure YAML inattendue : {raw[:300]}")

    return {
        "plan_id": data.get("plan_id", f"plan-{today}-001"),
        "plan_yaml": raw,
        "tasks": data.get("tasks", []),
    }


def review_conformance(handoff: dict, diff: str) -> dict[str, Any]:
    """
    Vérifie que le patch respecte le handoff.
    Retourne : {"passed": bool, "issues": list[str], "notes": str}
    """
    prompt = f"""Tu es un reviewer de conformité architecturale.
Réponds UNIQUEMENT avec un objet JSON valide, rien d'autre, pas de markdown.

Fichiers autorisés : {handoff.get("files_allowed", [])}
Chemins interdits : {handoff.get("paths_forbidden", [])}

Diff :
{diff[:2500]}

Critères : scope respecté, pas de fichier interdit modifié, pas de secret en dur.
Réponds exactement ainsi (JSON pur) :
{{"passed": true, "issues": [], "notes": "conformité OK"}}
"""

    raw = _call_claude(prompt)

    try:
        return _extract_json(_clean_markdown(raw))
    except (ValueError, json.JSONDecodeError):
        raw_lower = raw.lower()
        passed = "passed" in raw_lower and (
            '"passed": true' in raw_lower
            or "'passed': true" in raw_lower
            or "passed: true" in raw_lower
        )
        return {
            "passed": passed,
            "issues": [],
            "notes": raw[:200],
        }


def analyze_failure(  # patched
    ruff_out: str,
    mypy_out: str,
    test_out: str,
    diff: str,
    files_allowed: list[str],
    repo_path: str = ".",
) -> dict[str, Any]:
    """
    Analyse les échecs de validation et produit des hints précis pour Codex.

    Retourne :
    {
        "root_cause": str,          # Cause principale en une phrase
        "priority_errors": [        # Erreurs à corriger en priorité
            {"file": str, "line": int, "code": str, "message": str}
        ],
        "repair_hints": [str],      # Instructions précises pour Codex
        "files_to_fix": [str],      # Fichiers concernés (subset de files_allowed)
        "escalate": bool            # True si problème architectural hors scope Codex
    }
    """
    prompt = f"""Analyse ces erreurs Python. JSON uniquement, pas de markdown, réponse courte.

REPO: {repo_path}
FICHIERS: {files_allowed}
RUFF: {ruff_out[:300]}
MYPY: {mypy_out[:200]}
TESTS: {test_out[:200]}

Réponds en JSON sur une seule ligne :
{{"root_cause":"cause courte","repair_hints":["hint 1","hint 2"],"files_to_fix":["fichier.py"],"escalate":false}}
"""

    raw = _call_claude(prompt)

    try:
        result = _extract_json(_clean_markdown(raw))
        # Garantir la structure minimale
        result.setdefault("root_cause", "Erreurs de validation non analysées")
        result.setdefault("repair_hints", [])
        result.setdefault("files_to_fix", files_allowed)
        result.setdefault("escalate", False)
        # Ne pas escalader pour CWD/fichiers introuvables
        if result.get("escalate") and any(
            x in result.get("root_cause", "").lower()
            for x in ["introuvable", "not found", "existe pas"]
        ):
            result["escalate"] = False
        return result
    except Exception:
        return {
            "root_cause": "Analyse échouée — repair générique",
            "priority_errors": [],
            "repair_hints": [],
            "files_to_fix": files_allowed,
            "escalate": False,
        }
