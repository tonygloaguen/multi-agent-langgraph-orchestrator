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

## Commandes
- run    : docker compose up -d
- test   : make test  ou  pytest -q
- lint   : ruff check . && ruff format --check . && mypy orchestrator api --ignore-missing-imports
- build  : docker compose build
- ci     : act -j python-quality  (test local du workflow)
- audit  : /ci-audit

## Fichiers critiques (confirmation obligatoire avant modification)
- .env / .env.*
- orchestrator/  (schémas Pydantic, interfaces publiques)
- .github/workflows/ci.yml

## Contraintes spécifiques
- Pas de curl|bash ni wget|sh — binaires depuis releases taguées uniquement
- Actions GitHub : toujours pinnées sur tag sémantique vX.Y.Z (jamais @main/@master)
- Dependabot actif : github-actions + docker + pip (weekly, lundi)
- gitleaks-action épinglé sur v2.3.9

## Supply chain — procédure ajout nouvel outil CI
1. Identifier l'action officielle (pas un fork)
2. Trouver le dernier tag sémantique via : gh release list -R <owner>/<repo> --limit 5
3. Épingler sur vX.Y.Z dans le workflow
4. Dependabot trackera les mises à jour automatiquement
