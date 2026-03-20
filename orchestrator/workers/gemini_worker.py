from __future__ import annotations

from typing import Any

from orchestrator.config import get_settings

cfg = get_settings()


def is_available() -> bool:
    return bool(cfg.gemini_api_key and cfg.gemini_fallback_enabled)


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
        return _content_to_text(r.content)
    except Exception as e:
        return f"Gemini erreur : {e}"
