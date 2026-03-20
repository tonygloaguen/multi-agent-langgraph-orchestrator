# Multi-Agent Orchestrator — Documentation Technique & Maintenance

> Référence technique pour les équipes d'exploitation, de développement et d'intégration.

---

## Table des matières

1. [Architecture générale](#architecture-générale)
2. [Stack technique](#stack-technique)
3. [Structure du projet](#structure-du-projet)
4. [Le graphe LangGraph](#le-graphe-langgraph)
5. [Workers LLM](#workers-llm)
6. [Gestion d'état](#gestion-détat)
7. [Journalisation et traçabilité](#journalisation-et-traçabilité)
8. [Pipeline CI/CD](#pipeline-cicd)
9. [Déploiement Docker](#déploiement-docker)
10. [API Web (FastAPI + SSE)](#api-web-fastapi--sse)
11. [Opérations de maintenance](#opérations-de-maintenance)
12. [Ajout d'un agent / worker](#ajout-dun-agent--worker)
13. [Matrice de compatibilité](#matrice-de-compatibilité)
14. [Dépannage](#dépannage)

---

## Architecture générale

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATEUR                            │
│                                                                 │
│   ┌──────────┐    ┌─────────────────────────────────────────┐  │
│   │  API Web │    │           LangGraph State Machine        │  │
│   │ FastAPI  │───▶│                                          │  │
│   │  + SSE   │    │  INIT → PREFLIGHT → SNAPSHOT → PLAN     │  │
│   └──────────┘    │        ↓                                 │  │
│                   │  PREPARE_TASK → IMPLEMENT → VALIDATE     │  │
│                   │                    ↓                     │  │
│   ┌──────────┐    │              ANALYZE → REPAIR            │  │
│   │   Logs   │◀───│                    ↓                     │  │
│   │  JSONL   │    │          REVIEW → COMMIT → DONE          │  │
│   │  (HMAC)  │    └─────────────────────────────────────────┘  │
│   └──────────┘              │           │           │           │
│                             ▼           ▼           ▼           │
│                      ┌───────────┐ ┌────────┐ ┌─────────┐      │
│                      │  Claude   │ │ Codex  │ │ Gemini  │      │
│                      │ Code CLI  │ │  CLI   │ │(fallbk) │      │
│                      └───────────┘ └────────┘ └─────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Dépôt Git cible │
                    │  (branche agent/)│
                    └──────────────────┘
```

### Flux de données

```
goal (str)
    │
    ▼ node_snapshot
repo_snapshot (fichiers Python + git status)
    │
    ▼ node_plan [Claude]
plan YAML → tasks: [{id, description, files_allowed, acceptance_criteria}]
    │
    ▼ node_prepare_task
handoff YAML (fichier de passation pour Codex)
    │
    ▼ node_implement [Codex]
diff Git (code implémenté)
    │
    ▼ node_validate
{ruff_out, mypy_out, test_out, validation_passed}
    │
    ├── OK ──▶ node_review [Claude + Gitleaks]
    │          │
    │          └── OK ──▶ node_commit ──▶ node_done
    │
    └── KO ──▶ node_analyze [Claude]
               │
               └──▶ node_repair [Codex] ──▶ (retry validate)
                       │
                       └── max atteint ──▶ node_review ──▶ skip
```

---

## Stack technique

| Composant | Technologie | Version |
|---|---|---|
| Langage | Python | 3.11+ |
| Typage statique | mypy (strict) | dernière |
| Linter/formatter | Ruff | 0.11+ |
| Framework graphe | LangGraph | 0.2+ |
| Framework LLM | LangChain | 0.2+ |
| Validation données | Pydantic v2 | 2.6+ |
| LLM principal | Claude (Anthropic) | claude-opus-4-6 |
| LLM implémentation | Codex (OpenAI) | codex-mini-latest |
| LLM fallback | Gemini (Google) | gemini-2.0-flash |
| API Web | FastAPI | dernière |
| Streaming | Server-Sent Events | — |
| Scan secrets | Gitleaks | 8.24+ |
| Conteneurisation | Docker | multi-arch |
| Scan vulnérabilités | Trivy + Grype | dernières |
| Compression tokens | RTK | optionnel |

---

## Structure du projet

```
multi-agent-langgraph-orchestrator/
│
├── orchestrator/               # Package principal
│   ├── __init__.py
│   ├── config.py               # Settings Pydantic v2 (chargement .env)
│   ├── state_machine.py        # Graphe LangGraph + tous les nœuds
│   ├── state_machine_runner.py # Entrypoint CLI
│   ├── schemas/
│   │   └── __init__.py         # (extensible : schémas Pydantic partagés)
│   └── workers/
│       ├── __init__.py
│       ├── llm_provider.py     # Abstraction multi-provider (call_llm, fallback)
│       ├── claude_worker.py    # Planification, revue, analyse erreurs
│       ├── codex_worker.py     # Implémentation, repair
│       └── gemini_worker.py    # Fallback résumé/plan
│
├── api/
│   ├── server.py               # FastAPI + SSE (routes /api/run/*)
│   └── static/
│       └── index.html          # SPA minimaliste
│
├── scripts/
│   ├── bootstrap.sh            # Installation complète
│   ├── preflight.py            # Vérifications environnement
│   ├── start_orchestrator.sh   # Wrapper lancement
│   └── validate_task.sh        # ruff + mypy + pytest
│
├── tests/
│   ├── test_graph.py           # Structure du graphe LangGraph
│   ├── test_claude_worker.py   # Parsing, JSON extraction
│   ├── test_codex_worker.py    # Comptage erreurs, RTK, régression
│   ├── test_config.py          # Chargement settings
│   └── test_nis2_journal.py    # Signatures HMAC journal
│
├── docs/
│   ├── README.md               # Guide utilisateur
│   ├── MAINTENANCE.md          # Ce document
│   ├── SECURITE_NIS2_SECNUMCLOUD.md
│   └── deployment.md           # Notes déploiement
│
├── logs/                       # JSONL signés (créé au runtime)
├── .github/workflows/ci.yml    # Pipeline CI/CD GitHub Actions
├── .env.example                # Template configuration
├── .gitignore
├── .gitleaks.toml              # Configuration scan secrets
├── .pre-commit-config.yaml     # Hooks pre-commit
├── Makefile
├── Dockerfile
├── requirements.txt
└── CLAUDE.md                   # Règles projet (priorité maximale)
```

---

## Le graphe LangGraph

### Définition des nœuds

Le graphe est défini dans `orchestrator/state_machine.py`.

| Nœud | Fonction | Worker |
|---|---|---|
| `node_init` | Crée `run_id`, initialise état | — |
| `node_preflight` | Vérifie clés API, outils, dépôt Git | `preflight.py` |
| `node_snapshot` | Capture fichiers Python + git status | subprocess |
| `node_plan` | Génère plan YAML structuré | Claude / Gemini fallback |
| `node_prepare_task` | Écrit handoff YAML pour la tâche courante | — |
| `node_implement` | Implémente la tâche | Codex |
| `node_validate` | Exécute ruff, mypy, pytest | subprocess |
| `node_analyze` | Analyse les erreurs de validation | Claude |
| `node_repair` | Réimplémente avec guidance d'analyse | Codex |
| `node_review` | Revue conformité + scan Gitleaks | Claude |
| `node_commit` | `git add -A && git commit` | subprocess |
| `node_done` | Rapport final, écriture log | — |
| `node_skip_task` | Ignore la tâche courante, passe à la suivante | — |

### Routeurs conditionnels

```python
# Après preflight
route_after_preflight:
  errors → __end__
  OK     → node_snapshot

# Après validate
route_after_validate:
  validation_passed              → node_review
  not passed + repairs < max     → node_analyze
  not passed + repairs >= max    → node_review (avec flag)

# Après analyze
route_after_analyze:
  escalated (non réparable)      → node_review
  sinon                          → node_repair

# Après review
route_after_review:
  diff non vide + review_passed  → node_commit
  sinon                          → node_skip_task

# Après commit
route_after_commit:
  task_index < len(tasks)        → node_prepare_task (tâche suivante)
  sinon                          → node_done
```

### OrchestratorState (TypedDict)

```python
class OrchestratorState(TypedDict):
    run_id: str
    goal: str
    repo_path: str
    repo_snapshot: dict
    plan: dict                  # {plan_id, tasks: [...]}
    task_index: int
    current_task: dict          # {id, description, files_allowed, ...}
    handoff_path: str           # Chemin fichier YAML handoff
    diff: str                   # git diff après implement
    ruff_out: str
    mypy_out: str
    test_out: str
    validation_passed: bool
    repair_attempts: int
    analysis: dict              # {root_cause, repair_hints, files_to_fix, escalate}
    review: dict                # {passed, issues, notes}
    errors: list[str]
    events: list[dict]          # Journal structuré
```

---

## Workers LLM

### llm_provider.py — Couche d'abstraction

Tous les appels LLM passent par cette couche. Elle normalise les résultats
et gère le fallback automatique.

```python
# Appel simple
result: ProviderResult = call_llm(config, prompt, cwd=repo_path)

# Appel avec fallback automatique
result: ProviderResult = call_llm_with_fallback(
    prompt,
    providers=[("claude", claude_config), ("gemini", gemini_config)]
)
```

**Statuts de résultat :**

| Statut | Signification | Comportement |
|---|---|---|
| `SUCCESS` | Appel réussi | Utilise la sortie |
| `RATE_LIMITED` | Quota dépassé | Déclenche fallback |
| `TIMEOUT` | Délai dépassé | Déclenche fallback |
| `EMPTY_OUTPUT` | Réponse vide | Log warning + fallback |
| `PARSE_ERROR` | JSON invalide | Retry extraction regex |
| `TOOL_NOT_FOUND` | CLI absent | Erreur critique |

**Détection rate-limit (regex) :**
```
rate.limit | you've hit your limit | resets? at | usage limit
```

### claude_worker.py

Invoque le binaire `claude` en mode non-interactif (`--output-format stream-json`).

| Fonction | Entrée | Sortie |
|---|---|---|
| `generate_plan(goal, snapshot)` | objectif + snapshot repo | `{plan_id, tasks[]}` |
| `review_conformance(handoff, diff)` | fichier passation + diff | `{passed, issues, notes}` |
| `analyze_failure(ruff, mypy, test, diff, files)` | sorties validation | `{root_cause, repair_hints, files_to_fix, escalate}` |

**Extraction JSON robuste :**
1. Tentative `json.loads()` direct
2. Extraction regex sur `{...}` imbriqués (fallback)
3. Nettoyage marqueurs markdown (` ```json `)

### codex_worker.py

Invoque `codex exec --dangerously-bypass-approvals-and-sandbox`.

| Fonction | Notes |
|---|---|
| `implement_task(handoff, repo_path)` | Implémentation initiale |
| `repair_task(handoff, ..., attempt, analysis)` | Repair guidé avec contexte d'erreur |

**Protection régression :** Après chaque repair, le worker compte les erreurs
(ruff + mypy + pytest failures) avant/après. Si le count augmente, la branche
est automatiquement resetée (`git checkout -- .`).

**Intégration RTK :**
```python
def _rtk(cmd: list[str]) -> list[str]:
    """Wrap la commande avec rtk si disponible."""
    if shutil.which("rtk") and os.getenv("RTK_ENABLED", "true") == "true":
        return ["rtk"] + cmd
    return cmd
```

### gemini_worker.py

Utilise `langchain_google_genai.ChatGoogleGenerativeAI`. Réservé au fallback :
- `generate_plan()` : même contrat que `claude_worker.generate_plan()`
- `summarize_logs()` : résumé 5 lignes des logs (pour debugging)

> Gemini n'a **pas d'autorité architecturale**. Son plan est utilisé uniquement
> si Claude est indisponible (rate-limit, timeout).

---

## Gestion d'état

### Handoff YAML

Pour chaque tâche, l'orchestrateur génère un fichier YAML dans `orchestrator/handoffs/` :

```yaml
run_id: "abc123"
task_id: "add_auth_tests"
description: "Ajouter des tests unitaires pour le module auth"
files_allowed:
  - "src/auth.py"
  - "tests/test_auth.py"
acceptance_criteria:
  - "pytest passe sans erreur"
  - "coverage > 80%"
context: "..."   # Snapshot repo tronqué à ORCHESTRATOR_CONTEXT_MAX_TOKENS
repair_hints: [] # Rempli lors des repairs
attempt: 1
```

Ces fichiers sont **exclus de Git** (`.gitignore`).

### State runs (JSONL)

Chaque run produit `logs/<run_id>.jsonl`. Exemple d'entrée :

```json
{
  "event": "validate_failed",
  "run_id": "abc123",
  "task_id": "add_auth_tests",
  "attempt": 1,
  "ruff_errors": 3,
  "mypy_errors": 1,
  "test_failures": 2,
  "ts": "2026-03-20T14:23:45Z",
  "sig": "hmac-sha256:a1b2c3..."
}
```

La clé de signature est dans `.orchestrator_signing_key` (chmod 0o600, générée automatiquement).

---

## Journalisation et traçabilité

### Mécanisme HMAC-SHA256

Chaque événement est signé avant écriture :

```python
import hashlib, hmac, json

def sign_event(event: dict, key: bytes) -> str:
    payload = json.dumps(event, sort_keys=True).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()
```

La signature est ajoutée sous la clé `"sig"` dans chaque entrée JSONL.

### Vérification d'intégrité

```bash
# Vérifier qu'un fichier de log n'a pas été altéré
python3 -c "
import hmac, hashlib, json
key = open('.orchestrator_signing_key','rb').read()
for line in open('logs/<run_id>.jsonl'):
    entry = json.loads(line)
    sig = entry.pop('sig')
    expected = hmac.new(key, json.dumps(entry,sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert sig == expected, f'Signature invalide : {entry}'
print('Toutes les signatures OK')
"
```

### Niveaux de log

| Niveau | Cas d'usage |
|---|---|
| `INFO` | Progression normale (plan, implement, commit) |
| `WARN` | Repair loop, fallback activé, tâche ignorée |
| `ERROR` | Preflight échoué, timeout, clé absente |

---

## Pipeline CI/CD

Fichier : `.github/workflows/ci.yml`

```
Push / PR
    │
    ├── Job: gitleaks          → Scan secrets (actions/gitleaks-action@v2)
    │
    ├── Job: python-quality    → Ruff check + format
    │                          → Mypy strict
    │                          → Pytest -q
    │
    ├── Job: docker-build      → Build image multi-arch (linux/amd64, linux/arm64)
    │                          → Cache GitHub Actions
    │
    ├── Job: trivy-image       → Scan CVE HIGH/CRITICAL (Aqua Security Trivy)
    │
    └── Job: grype-image       → Scan CVE --only-fixed (Anchore Grype)
```

**Règle : aucun merge sans green CI.**

### Pre-commit hooks (`.pre-commit-config.yaml`)

Exécutés localement avant chaque commit :

| Hook | Action |
|---|---|
| `end-of-file-fixer` | Assure une newline finale |
| `trailing-whitespace` | Supprime espaces en fin de ligne |
| `check-yaml` | Valide la syntaxe YAML |
| `check-json` | Valide la syntaxe JSON |
| `check-merge-conflict` | Bloque les marqueurs de conflit |
| `detect-private-key` | Bloque les clés privées |
| `ruff-rtk` | Lint Python (ruff check --fix) + RTK si disponible |
| `ruff-format-rtk` | Format Python (ruff format) + RTK si disponible |
| `gitleaks` | Scan secrets complet |

Installation des hooks :
```bash
pip install pre-commit
pre-commit install
```

---

## Déploiement Docker

### Build

```bash
docker build -t multi-agent-orchestrator .
```

### Run

```bash
docker run -d \
  --env-file .env \
  -p 8080:8080 \
  --name orchestrator \
  multi-agent-orchestrator
```

### Détails Dockerfile

```
Base : python:3.13-slim
Port : 8080 (uvicorn api.server:app)
User : non-root (recommandé pour prod)
```

### Variables d'environnement Docker

Toutes les variables de `.env.example` sont supportées.
En production, utiliser un gestionnaire de secrets (Vault, AWS SSM, etc.)
plutôt que `--env-file`.

---

## API Web (FastAPI + SSE)

### Routes disponibles

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/api/run` | Lancer un run (`{"goal": "...", "repo_path": "..."}`) |
| `GET` | `/api/run/status` | Statut du run actif |
| `GET` | `/api/run/history` | Historique des runs (depuis JSONL) |
| `GET` | `/api/run/logs` | Stream SSE des logs en temps réel |
| `POST` | `/api/run/stop` | Arrêter le run actif |

### SSE — Format des événements

```
data: {"event": "node_entered", "node": "node_implement", "task": "...", "ts": "..."}

data: {"event": "validate_failed", "errors": 3, "ts": "..."}

data: {"event": "done", "status": "success", "commits": 2, "ts": "..."}
```

Heartbeat toutes les 15 secondes si pas d'événement :
```
data: {"heartbeat": true}
```

### Limitations

- **1 seul run actif à la fois** (semaphore en mémoire)
- L'état est en mémoire : un redémarrage efface le run actif
- L'historique est reconstruit depuis les fichiers JSONL au démarrage

---

## Opérations de maintenance

### Rotation de la clé de signature HMAC

```bash
# Supprimer l'ancienne clé (les anciens logs ne seront plus vérifiables)
rm .orchestrator_signing_key
# La nouvelle clé sera générée automatiquement au prochain run
```

> **Attention** : Archiver les anciens logs avant rotation si la vérification
> d'intégrité historique est requise (conformité NIS2).

### Nettoyage des logs

```bash
make clean         # Supprime caches, handoffs, logs
# Ou manuellement :
find logs/ -name "*.jsonl" -mtime +90 -delete  # Supprimer logs > 90 jours
```

### Mise à jour des dépendances

```bash
# Vérifier les mises à jour disponibles
pip list --outdated

# Mettre à jour (tester en staging d'abord)
pip install --upgrade langgraph langchain-anthropic pydantic
pip freeze > requirements.txt

# Valider
make validate
```

### Mise à jour des modèles LLM

Modifier dans `.env` :
```dotenv
CLAUDE_MODEL=claude-opus-4-6      # Vérifier disponibilité API
CODEX_MODEL=codex-mini-latest
GEMINI_MODEL=gemini-2.0-flash
```

### Monitoring

Points à surveiller en production :

| Métrique | Source | Seuil d'alerte |
|---|---|---|
| Durée d'un run | logs JSONL `ts` delta | > 30 min |
| Taux de skip_task | count events `task_skipped` | > 30% |
| Taux d'appel fallback Gemini | count events `fallback_triggered` | > 20% |
| Erreurs preflight | count events `preflight_error` | > 0 |
| Taille des logs | `du -sh logs/` | > 10 GB |

---

## Ajout d'un agent / worker

Pour intégrer un nouveau LLM (ex: Mistral) :

1. **Créer** `orchestrator/workers/mistral_worker.py` avec les mêmes signatures
   que `claude_worker.py` :
   ```python
   def generate_plan(goal: str, repo_snapshot: dict) -> dict: ...
   def review_conformance(handoff: dict, diff: str) -> dict: ...
   def analyze_failure(...) -> dict: ...
   ```

2. **Ajouter** les variables de config dans `orchestrator/config.py` (Pydantic) :
   ```python
   mistral_api_key: SecretStr | None = None
   mistral_model: str = "mistral-large-latest"
   ```

3. **Enregistrer** le provider dans `llm_provider.py` (liste `PROVIDERS`).

4. **Documenter** le rôle dans `CLAUDE.md`.

5. **Tester** : ajouter `tests/test_mistral_worker.py`.

> **Règle CLAUDE.md** : Toute modification de schéma Pydantic ou d'interface
> publique doit être validée par Claude Code avant merge.

---

## Matrice de compatibilité

| Composant | Testé | Supporté | Notes |
|---|---|---|---|
| Python 3.11 | Oui | Oui | Version minimale requise |
| Python 3.12 | Oui (CI) | Oui | Recommandé |
| Python 3.13 | Partiel | Oui (Docker) | Image base Dockerfile |
| LangGraph 0.2.x | Oui | Oui | API stable |
| LangGraph 0.3.x | Non testé | À valider | Breaking changes possibles |
| Pydantic v2 | Oui | Oui | v1 non supportée |
| Claude claude-opus-4-6 | Oui | Oui | Modèle recommandé |
| Claude claude-sonnet-4-6 | Oui | Oui | Alternative (moins coûteux) |
| Codex codex-mini-latest | Oui | Oui | |
| Gemini 2.0 Flash | Oui | Oui (fallback) | |
| Docker linux/amd64 | Oui (CI) | Oui | |
| Docker linux/arm64 | Oui (CI) | Oui | Apple Silicon |
| macOS (brew) | Oui | Oui | |
| Ubuntu 22.04+ | Oui | Oui | |
| Windows WSL2 | Partiel | Best-effort | Chemins absolus à adapter |

---

## Dépannage

### Problème : `ModuleNotFoundError: No module named 'langgraph'`

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Problème : `FileNotFoundError: .orchestrator_signing_key`

La clé HMAC est générée automatiquement au premier run. Si le fichier est
absent manuellement, relancer un run et il sera recréé.

### Problème : `mypy` strict échoue sur un nouveau fichier

Ajouter les annotations de type manquantes. Références :
- [Mypy cheatsheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
- Utiliser `reveal_type(x)` pour diagnostiquer

### Problème : Gitleaks bloque un faux positif

Ajouter le pattern dans `.gitleaks.toml` > `[allowlist]` > `regexes` :
```toml
[[allowlist.regexes]]
description = "Token de test factice"
regex = '''mon_token_de_test_[a-z]+'''
```

### Problème : run bloqué (pas de sortie depuis > 5 min)

```bash
make stop   # Arrête via pkill
# Vérifier les logs
tail -f logs/<run_id>.jsonl
```

### Problème : repair loop infini apparent

Vérifier `ORCHESTRATOR_MAX_REPAIR_LOOPS` dans `.env` (max 5 enforced par Pydantic).
Un run ne peut pas boucler indéfiniment.
