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
