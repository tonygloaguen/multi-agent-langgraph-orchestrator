from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from orchestrator.config import get_settings

cfg = get_settings()


def is_available() -> bool:
    return bool(cfg.gemini_api_key_value and cfg.gemini_fallback_enabled)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                parts.append(text if isinstance(text, str) else str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)

    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        return str(content)

    return str(content)


def generate_plan(goal: str, repo_snapshot: str) -> dict[str, Any]:
    """Génère un plan structuré via Gemini (fallback si Claude est rate-limited).

    Même contrat que claude_worker.generate_plan :
    Retourne {"plan_id": str, "plan_yaml": str, "tasks": list}.
    """
    import yaml

    if not is_available():
        raise RuntimeError("Gemini non configuré (GEMINI_API_KEY manquante ou fallback désactivé)")

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

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=cfg.gemini_model,
            google_api_key=cfg.gemini_api_key_value,
            max_output_tokens=4096,
        )
        r = llm.invoke(prompt)
        raw: str = _content_to_text(r.content).strip()
    except Exception as exc:
        raise RuntimeError(f"Gemini erreur lors de la planification : {exc}") from exc

    # Nettoyer d'éventuelles balises markdown
    if "```" in raw:
        lines = raw.split("\n")
        cleaned = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            cleaned.append(line)
        raw = "\n".join(cleaned).strip()

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Gemini YAML invalide : {exc}\n\nRaw:\n{raw[:500]}") from exc

    if not isinstance(data, dict) or "tasks" not in data:
        raise RuntimeError(f"Structure YAML Gemini inattendue : {raw[:300]}")

    return {
        "plan_id": data.get("plan_id", f"plan-{today}-001"),
        "plan_yaml": raw,
        "tasks": data.get("tasks", []),
    }


def summarize_logs(logs: str) -> str:
    if not is_available():
        return "Gemini non configuré (GEMINI_API_KEY manquante)"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=cfg.gemini_model,
            google_api_key=cfg.gemini_api_key_value,
            max_output_tokens=500,
        )
        r = llm.invoke(
            f"Résume en 5 lignes max, identifie la cause principale :\n{logs[:2000]}"
        )
        return _content_to_text(r.content)
    except Exception as e:
        return f"Gemini erreur : {e}"
