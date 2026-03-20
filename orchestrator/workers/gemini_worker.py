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
