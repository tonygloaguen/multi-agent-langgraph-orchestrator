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
8. [Sécurité API](#sécurité-api)
9. [Pipeline CI/CD](#pipeline-cicd)
10. [Déploiement Docker](#déploiement-docker)
11. [API Web (FastAPI + SSE)](#api-web-fastapi--sse)
12. [Opérations de maintenance](#opérations-de-maintenance)
13. [Ajout d'un agent / worker](#ajout-dun-agent--worker)
14. [Matrice de compatibilité](#matrice-de-compatibilité)
15. [Dépannage](#dépannage)

---

## Architecture générale

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATEUR                            │
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  API Web (FastAPI + SSE)                                 │  │
│   │  ┌────────────┐  ┌──────────┐  ┌──────────────────────┐ │  │
│   │  │ Auth Bearer│  │  RBAC   │  │  Rate Limiting (IP)  │ │  │
│   │  │ HMAC timing│  │ 3 rôles │  │  slowapi             │ │  │
│   │  └────────────┘  └──────────┘  └──────────────────────┘ │  │
│   │  ┌────────────────────────────────────────────────────┐  │  │
│   │  │ Input Validation  │  Security Headers  │  CORS     │  │  │
│   │  └────────────────────────────────────────────────────┘  │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│                   ┌──────────────────────┐                       │
│                   │  LangGraph State     │                       │
│                   │  Machine             │                       │
│                   │  INIT → PREFLIGHT   │                       │
│                   │  → SNAPSHOT → PLAN  │                       │
│                   │  → IMPLEMENT        │                       │
│                   │  → VALIDATE         │                       │
│                   │  → REVIEW → COMMIT  │                       │
│                   │  → DONE             │                       │
│                   └──────────────────────┘                       │
│                        │         │         │                     │
│                        ▼         ▼         ▼                     │
│                 ┌───────────┐ ┌──────┐ ┌────────┐               │
│                 │  Claude   │ │Codex │ │ Gemini │               │
│                 │ Code CLI  │ │ CLI  │ │(fallbk)│               │
│                 └───────────┘ └──────┘ └────────┘               │
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Logs                                                    │  │
│   │  logs/<run_id>.jsonl   (HMAC-SHA256, événements)         │  │
│   │  logs/audit.jsonl      (HMAC-SHA256, accès HTTP/API)     │  │
│   └──────────────────────────────────────────────────────────┘  │
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
goal (str) → validation anti-injection
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
| Auth API | Bearer token (HMAC timing-safe) | — |
| RBAC | 3 rôles : admin / operator / reader | — |
| Rate limiting | slowapi (par IP) | dernière |
| Streaming | Server-Sent Events | — |
| Scan secrets | Gitleaks | 8.24+ |
| SAST Python | Bandit | dernière |
| Audit dépendances | pip-audit | dernière |
| Conteneurisation | Docker | multi-arch |
| Scan vulnérabilités | Trivy + Grype | dernières |
| SBOM | CycloneDX (Python) + syft (image) | — |
| Compression tokens | RTK | optionnel |

---

## Structure du projet

```
multi-agent-langgraph-orchestrator/
│
├── orchestrator/               # Package principal
│   ├── __init__.py
│   ├── config.py               # Settings Pydantic v2 — SecretStr sur toutes les clés
│   ├── state_machine.py        # Graphe LangGraph + tous les nœuds
│   ├── state_machine_runner.py # Entrypoint CLI
│   ├── schemas/
│   │   └── __init__.py
│   └── workers/
│       ├── __init__.py
│       ├── llm_provider.py     # Abstraction multi-provider (call_llm, fallback)
│       ├── claude_worker.py    # Planification, revue, analyse erreurs
│       ├── codex_worker.py     # Implémentation, repair
│       └── gemini_worker.py    # Fallback résumé/plan
│
├── api/
│   ├── server.py               # FastAPI + SSE + auth + RBAC + rate limiting + audit
│   ├── security.py             # Middleware auth Bearer, RBAC, validation entrées
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
│   ├── test_nis2_journal.py    # Signatures HMAC journal
│   ├── test_api_security.py    # Auth Bearer, RBAC, timing-safe, rate limit
│   └── test_input_validation.py # Anti-injection, payloads malveillants
│
├── docs/
│   ├── README.md               # Guide utilisateur (auth, tokens, RBAC, FAQ)
│   ├── MAINTENANCE.md          # Ce document
│   ├── SECURITE_NIS2_SECNUMCLOUD.md
│   ├── INCIDENT_RESPONSE.md    # Procédures IR + scripts bash + matrice RACI
│   ├── SECURITY_DECISIONS.md   # ADR — arbitrages sécurité documentés
│   └── deployment.md           # Notes déploiement
│
├── logs/                       # JSONL signés HMAC (créé au runtime)
│   ├── <run_id>.jsonl          # Événements d'orchestration
│   └── audit.jsonl             # Audit log HTTP/API (IP, rôle, path, statut)
│
├── .github/workflows/ci.yml    # Pipeline CI/CD avec security gates
├── .env.example                # Template configuration (avec nouveaux secrets auth)
├── .gitignore
├── .gitleaks.toml
├── .pre-commit-config.yaml
├── Makefile
├── Dockerfile
├── requirements.txt
└── CLAUDE.md
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
    plan: dict
    task_index: int
    current_task: dict
    handoff_path: str
    diff: str
    ruff_out: str
    mypy_out: str
    test_out: str
    validation_passed: bool
    repair_attempts: int
    analysis: dict
    review: dict
    errors: list[str]
    events: list[dict]
```

---

## Workers LLM

### llm_provider.py — Couche d'abstraction

Tous les appels LLM passent par cette couche.

```python
result: ProviderResult = call_llm(config, prompt, cwd=repo_path)
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

### claude_worker.py

Invoque le binaire `claude` en mode non-interactif (`--output-format stream-json`).
Les clés API sont transmises via `.get_secret_value()` uniquement à l'invocation,
jamais stockées en variable intermédiaire.

| Fonction | Entrée | Sortie |
|---|---|---|
| `generate_plan(goal, snapshot)` | objectif + snapshot repo | `{plan_id, tasks[]}` |
| `review_conformance(handoff, diff)` | fichier passation + diff | `{passed, issues, notes}` |
| `analyze_failure(ruff, mypy, test, diff, files)` | sorties validation | `{root_cause, repair_hints, files_to_fix, escalate}` |

### codex_worker.py

Invoque `codex exec --dangerously-bypass-approvals-and-sandbox`.

| Fonction | Notes |
|---|---|
| `implement_task(handoff, repo_path)` | Implémentation initiale |
| `repair_task(handoff, ..., attempt, analysis)` | Repair guidé avec contexte d'erreur |

**Protection régression :** Après chaque repair, le worker compare le nombre
d'erreurs avant/après. Si ça empire : `git checkout -- .` automatique.

**Intégration RTK :**
```python
def _rtk(cmd: list[str]) -> list[str]:
    if shutil.which("rtk") and os.getenv("RTK_ENABLED", "true") == "true":
        return ["rtk"] + cmd
    return cmd
```

### gemini_worker.py

Fallback uniquement. N'a pas d'autorité architecturale.

---

## Gestion d'état

### Handoff YAML

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
context: "..."
repair_hints: []
attempt: 1
```

Fichiers exclus de Git (`.gitignore`).

### State runs (JSONL)

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

### Audit log HTTP (logs/audit.jsonl)

Chaque requête API produit une entrée signée :

```json
{
  "ts": "2026-03-22T10:15:30Z",
  "ip": "192.168.1.10",
  "role": "operator",
  "method": "POST",
  "path": "/api/run",
  "status": 200,
  "duration_ms": 42,
  "sig": "hmac-sha256:d4e5f6..."
}
```

Les tokens Bearer ne sont **jamais** journalisés. Les security events
(401, 403, 429) sont marqués `"security_event": true`.

---

## Journalisation et traçabilité

### Mécanisme HMAC-SHA256

Appliqué à **deux niveaux** : événements orchestration + accès HTTP.

```python
def sign_event(event: dict, key: bytes) -> str:
    payload = json.dumps(event, sort_keys=True).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()
```

### Vérification d'intégrité

```bash
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
| `SECURITY` | Auth échouée, violation RBAC, payload suspect, rate limit |

---

## Sécurité API

### Authentification Bearer

L'API exige un token Bearer sur tous les endpoints sensibles.
La comparaison est faite via `hmac.compare_digest` (timing-safe, résistant aux timing attacks).

```bash
# Appel authentifié
curl -H "Authorization: Bearer <token>" http://localhost:8080/api/run/status
```

Les tokens sont configurés via variables d'environnement (voir `.env.example`).
Jamais loggés, jamais exposés dans les réponses d'erreur.

### RBAC — 3 rôles

| Rôle | Actions autorisées |
|---|---|
| `admin` | Tout (run, stop, status, history, logs) |
| `operator` | Lancer un run, consulter status et logs |
| `reader` | Consulter status et history uniquement |

Chaque endpoint déclare ses rôles requis via `Depends(require_roles(...))`.
Une violation RBAC retourne HTTP 403 et génère un `security_event` dans audit.jsonl.

### Rate limiting

Configurable via `.env` :

```dotenv
RATE_LIMIT_RUN=5/minute      # POST /api/run
RATE_LIMIT_DEFAULT=60/minute # Autres endpoints
```

Dépassement → HTTP 429 + entrée audit avec `security_event: true`.

### Validation des entrées

Le champ `goal` est validé contre 12 patterns d'injection connus :

- `ignore.*instructions`, `exfiltrate`, `<system>`, `[INST]`, etc.
- Longueur max : 2000 caractères
- `repo_path` : blocage des caractères shell dangereux (`;`, `&`, `|`, `` ` ``, `$`, etc.)

Payload rejeté → HTTP 422 + log security_event.

### Headers de sécurité

Ajoutés automatiquement par middleware sur toutes les réponses :

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'
Server: (supprimé)
```

CORS restreint à `CORS_ALLOWED_ORIGINS` (plus de wildcard `*`).

### Génération des tokens

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Variables d'environnement à définir dans `.env` :

```dotenv
AUTH_ENABLED=true
API_TOKEN_ADMIN=<token-généré>
API_TOKEN_OPERATOR=<token-généré>
API_TOKEN_READER=<token-généré>
CORS_ALLOWED_ORIGINS=https://votre-domaine.com
```

---

## Pipeline CI/CD

Fichier : `.github/workflows/ci.yml`

```
Push / PR
    │
    ├── Job: gitleaks          → Scan secrets (gitleaks/gitleaks-action@v2.3.9)
    │
    ├── Job: python-quality    → Ruff check + format
    │                          → Mypy strict
    │                          → Pytest -q (96 tests)
    │
    ├── Job: bandit-sast       → Analyse statique sécurité Python (medium+)
    │                          → Échec sur HIGH/CRITICAL
    │
    ├── Job: pip-audit         → CVE sur dépendances Python
    │                          → Échec si vulnérabilité fixable détectée
    │
    ├── Job: docker-build      → Build image multi-arch (linux/amd64, linux/arm64)
    │
    ├── Job: trivy-image       → SARIF upload + security gate CRITICAL (exit-code 1)
    │
    ├── Job: grype-image       → Scan CVE --only-fixed
    │
    ├── Job: sbom-python       → CycloneDX (archivé 90j comme artefact CI)
    │
    └── Job: sbom-image        → syft image Docker (archivé 90j comme artefact CI)
```

**Security gates actifs :** le pipeline échoue si :
- secrets détectés (Gitleaks)
- vulnérabilité CRITICAL dans l'image Docker (Trivy)
- CVE fixable dans les dépendances Python (pip-audit)
- test de sécurité échoué (pytest test_api_security.py, test_input_validation.py)
- Bandit détecte un problème HIGH ou CRITICAL

**Règle : aucun merge sans green CI.**

### Pre-commit hooks

| Hook | Action |
|---|---|
| `end-of-file-fixer` | Assure une newline finale |
| `trailing-whitespace` | Supprime espaces en fin de ligne |
| `check-yaml` | Valide la syntaxe YAML |
| `check-json` | Valide la syntaxe JSON |
| `check-merge-conflict` | Bloque les marqueurs de conflit |
| `detect-private-key` | Bloque les clés privées |
| `ruff-rtk` | Lint Python (ruff check --fix) |
| `ruff-format-rtk` | Format Python (ruff format) |
| `gitleaks` | Scan secrets complet |

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

> En production, ne pas utiliser `--env-file` : injecter les secrets via
> un gestionnaire dédié (Vault, AWS SSM, Docker Secrets).

### Variables d'environnement requises

Voir `.env.example` pour la liste complète. Variables critiques à définir :

```dotenv
# Authentification API (obligatoire si AUTH_ENABLED=true)
AUTH_ENABLED=true
API_TOKEN_ADMIN=<token-urlsafe-32>
API_TOKEN_OPERATOR=<token-urlsafe-32>
API_TOKEN_READER=<token-urlsafe-32>

# LLM providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# CORS (production)
CORS_ALLOWED_ORIGINS=https://votre-domaine.com

# Rate limiting
RATE_LIMIT_RUN=5/minute
RATE_LIMIT_DEFAULT=60/minute
```

---

## API Web (FastAPI + SSE)

### Routes disponibles

| Méthode | Route | Rôles requis | Description |
|---|---|---|---|
| `POST` | `/api/run` | admin, operator | Lancer un run |
| `GET` | `/api/run/status` | admin, operator, reader | Statut du run actif |
| `GET` | `/api/run/history` | admin, operator, reader | Historique des runs |
| `GET` | `/api/run/logs` | admin, operator | Stream SSE des logs |
| `POST` | `/api/run/stop` | admin | Arrêter le run actif |

### SSE — Format des événements

```
data: {"event": "node_entered", "node": "node_implement", "task": "...", "ts": "..."}
data: {"event": "validate_failed", "errors": 3, "ts": "..."}
data: {"event": "done", "status": "success", "commits": 2, "ts": "..."}
```

Heartbeat toutes les 15 secondes :
```
data: {"heartbeat": true}
```

### Limitations

- 1 seul run actif à la fois (semaphore en mémoire)
- L'état est en mémoire : un redémarrage efface le run actif
- Le rate limiting est en mémoire : réinitialisé au restart (utiliser Redis pour multi-instance)
- L'historique est reconstruit depuis les fichiers JSONL au démarrage

---

## Opérations de maintenance

### Rotation de la clé de signature HMAC

```bash
# Archiver les anciens logs avant rotation (intégrité historique)
cp -r logs/ logs_archive_$(date +%Y%m%d)/

# Supprimer l'ancienne clé
rm .orchestrator_signing_key
# La nouvelle clé sera générée automatiquement au prochain run
```

> **Attention NIS2 :** Les anciens logs ne seront plus vérifiables avec la nouvelle clé.
> Archiver systématiquement avant rotation si la conformité l'exige.

### Rotation des tokens API

```bash
# Générer de nouveaux tokens
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Mettre à jour .env (ou le gestionnaire de secrets en prod)
# Redémarrer le service pour prendre en compte les nouveaux tokens
docker restart orchestrator
```

> Les anciens tokens sont immédiatement invalides après redémarrage.
> Voir `docs/INCIDENT_RESPONSE.md` pour la procédure en cas de compromission.

### Nettoyage des logs

```bash
make clean         # Supprime caches, handoffs, logs
# Ou sélectif :
find logs/ -name "*.jsonl" -mtime +90 -delete  # Supprimer logs > 90 jours
```

> Conserver `logs/audit.jsonl` selon la durée de rétention définie par votre
> politique de conformité (NIS2 recommande 12 mois minimum).

### Mise à jour des dépendances

```bash
# Vérifier les CVE sur les dépendances actuelles
pip-audit

# Vérifier les mises à jour disponibles
pip list --outdated

# Mettre à jour (tester en staging d'abord)
pip install --upgrade langgraph langchain-anthropic pydantic
pip freeze > requirements.txt

# Valider
make validate
```

### Régénération du SBOM

```bash
# SBOM Python
pip install cyclonedx-bom
cyclonedx-py -e --format json -o sbom-python.json

# SBOM image Docker
syft multi-agent-orchestrator:latest -o cyclonedx-json > sbom-image.json
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
| Tentatives auth échouées | audit.jsonl security_event 401 | > 5 / 5 min |
| Violations RBAC | audit.jsonl security_event 403 | > 0 |
| Rate limit hits | audit.jsonl security_event 429 | > 10 / min |
| Payload rejetés (injection) | audit.jsonl security_event 422 | > 0 |

---

## Ajout d'un agent / worker

Pour intégrer un nouveau LLM (ex: Mistral) :

1. **Créer** `orchestrator/workers/mistral_worker.py` avec les mêmes signatures :
   ```python
   def generate_plan(goal: str, repo_snapshot: dict) -> dict: ...
   def review_conformance(handoff: dict, diff: str) -> dict: ...
   def analyze_failure(...) -> dict: ...
   ```

2. **Ajouter** les variables dans `orchestrator/config.py` en `SecretStr` :
   ```python
   mistral_api_key: SecretStr | None = None
   mistral_model: str = "mistral-large-latest"
   ```

3. **Enregistrer** dans `llm_provider.py` (liste `PROVIDERS`).

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
| Claude claude-sonnet-4-6 | Oui | Oui | Alternative moins coûteuse |
| Codex codex-mini-latest | Oui | Oui | |
| Gemini 2.0 Flash | Oui | Oui (fallback) | |
| Docker linux/amd64 | Oui (CI) | Oui | |
| Docker linux/arm64 | Oui (CI) | Oui | Apple Silicon / RPi 4 |
| macOS (brew) | Oui | Oui | |
| Ubuntu 22.04+ | Oui | Oui | |
| Windows WSL2 | Partiel | Best-effort | Chemins absolus à adapter |

---

## Dépannage

### Problème : `401 Unauthorized` sur l'API

Vérifier que `AUTH_ENABLED=true` et que le token est correct dans `.env`.
Tester :
```bash
curl -H "Authorization: Bearer <API_TOKEN_OPERATOR>" http://localhost:8080/api/run/status
```

### Problème : `403 Forbidden` sur un endpoint

Le rôle du token utilisé n'a pas accès à cet endpoint.
Consulter la table des rôles dans la section [RBAC](#rbac--3-rôles).

### Problème : `429 Too Many Requests`

Rate limit atteint. Attendre la fenêtre ou ajuster `RATE_LIMIT_*` dans `.env`.
Pour un déploiement multi-instance, configurer Redis comme backend slowapi.

### Problème : `ModuleNotFoundError: No module named 'langgraph'`

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Problème : `FileNotFoundError: .orchestrator_signing_key`

La clé est générée automatiquement au premier run. Si absente, relancer un run.

### Problème : signature HMAC invalide sur un log

Log potentiellement altéré. Suivre la procédure `docs/INCIDENT_RESPONSE.md`
section "Suspicion de falsification de logs".

### Problème : `mypy` strict échoue sur un nouveau fichier

Ajouter les annotations de type manquantes.
Utiliser `reveal_type(x)` pour diagnostiquer.

### Problème : Gitleaks bloque un faux positif

```toml
# .gitleaks.toml > [allowlist]
[[allowlist.regexes]]
description = "Token de test factice"
regex = '''mon_token_de_test_[a-z]+'''
```

### Problème : run bloqué (pas de sortie depuis > 5 min)

```bash
make stop
tail -f logs/<run_id>.jsonl
```

### Problème : repair loop infini apparent

Vérifier `ORCHESTRATOR_MAX_REPAIR_LOOPS` dans `.env` (max 5 enforced par Pydantic).
