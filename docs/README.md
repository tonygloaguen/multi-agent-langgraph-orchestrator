# Multi-Agent Orchestrator — Guide Utilisateur

> Orchestrateur de code piloté par LLM : Claude Code + Codex CLI + Gemini, coordonnés par LangGraph.

---

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Prérequis](#prérequis)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Lancer un run](#lancer-un-run)
6. [Interface web](#interface-web)
7. [Comprendre les résultats](#comprendre-les-résultats)
8. [Commandes utiles](#commandes-utiles)
9. [Questions fréquentes](#questions-fréquentes)

---

## Vue d'ensemble

Le Multi-Agent Orchestrator automatise la réalisation de tâches de développement sur un dépôt Git existant :

```
Vous donnez un objectif → l'orchestrateur planifie, code, valide et committe
```

### Ce que fait l'orchestrateur

1. **Analyse** votre dépôt (fichiers Python, état Git)
2. **Planifie** les tâches via Claude (plan YAML structuré)
3. **Implémente** chaque tâche via Codex CLI
4. **Valide** automatiquement (Ruff lint, Mypy types, Pytest)
5. **Répare** les erreurs en boucle guidée (jusqu'à N tentatives)
6. **Revoit** la conformité et scanne les secrets via Claude + Gitleaks
7. **Committe** le code validé sur une branche `agent/`

### Agents impliqués

| Agent | Rôle | Quand il intervient |
|---|---|---|
| **Claude Code CLI** | Planification, revue, analyse d'erreurs | Plan, Review, Analyze |
| **Codex CLI** | Implémentation, repair de code | Implement, Repair |
| **Gemini 2.0 Flash** | Fallback résumé/triage | Rate-limit Claude uniquement |

---

## Prérequis

| Outil | Version minimale | Vérification |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Claude Code CLI | dernière | `claude --version` |
| Codex CLI | dernière | `codex --version` |
| Git | 2.40+ | `git --version` |

**Clés API requises :**
- `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com)
- `OPENAI_API_KEY` — [platform.openai.com](https://platform.openai.com)

**Clé API optionnelle :**
- `GEMINI_API_KEY` — [aistudio.google.com](https://aistudio.google.com) (fallback rate-limit)

---

## Installation

```bash
# 1. Cloner le dépôt
git clone <url-du-repo>
cd multi-agent-langgraph-orchestrator

# 2. Lancer le bootstrap (tout-en-un)
bash scripts/bootstrap.sh
```

Le bootstrap effectue automatiquement :
- Vérification Python 3.11+, Node/npm
- Création du fichier `.env` depuis `.env.example`
- Création du virtualenv `.venv`
- Installation des dépendances Python
- Vérification des imports
- Vérification Claude CLI et Codex CLI
- Activation du hook RTK (si installé)

> **Attention** : À l'étape `.env`, le script s'arrête pour vous laisser renseigner
> vos clés API. C'est **obligatoire** avant de continuer.

---

## Configuration

Éditez le fichier `.env` (créé par le bootstrap) :

```dotenv
# Clés API (obligatoires)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Clé optionnelle (fallback si Claude est en rate-limit)
GEMINI_API_KEY=...

# Modèles utilisés (valeurs par défaut recommandées)
CLAUDE_MODEL=claude-opus-4-6
CODEX_MODEL=codex-mini-latest
GEMINI_MODEL=gemini-2.0-flash

# Comportement de l'orchestrateur
ORCHESTRATOR_MAX_REPAIR_LOOPS=2     # Tentatives de repair max (1–5)
ORCHESTRATOR_TASK_TIMEOUT=300       # Timeout par tâche en secondes
ORCHESTRATOR_CONTEXT_MAX_TOKENS=8000

# Fonctionnalités
GEMINI_FALLBACK_ENABLED=true        # Activer le fallback Gemini
RTK_ENABLED=true                    # Compression tokens LLM (optionnel)

# Dépôt cible
DEFAULT_REPO_PATH=.                 # Chemin du dépôt à traiter
GIT_AGENT_BRANCH_PREFIX=agent/      # Préfixe des branches créées
```

### Paramètres importants

| Paramètre | Valeur par défaut | Effet |
|---|---|---|
| `ORCHESTRATOR_MAX_REPAIR_LOOPS` | `2` | Augmenter si les tâches sont complexes (max 5) |
| `ORCHESTRATOR_TASK_TIMEOUT` | `300` | Augmenter pour les gros dépôts |
| `DEFAULT_REPO_PATH` | `.` | Pointer vers le dépôt à traiter |

---

## Lancer un run

### Via la ligne de commande

```bash
# Activer le venv si nécessaire
source .venv/bin/activate

# Lancement rapide
make run

# Ou directement avec un objectif
python -m orchestrator.state_machine_runner --goal "Ajouter des tests unitaires pour le module auth"
```

### Via l'interface web

```bash
make start   # Lance le serveur API sur http://localhost:8080
```

Puis ouvrir [http://localhost:8080](http://localhost:8080).

### Via VS Code

1. Ouvrir le dossier du projet dans VS Code
2. Cliquer "Allow" sur la notification d'extension
3. L'orchestrateur se lance automatiquement (tâche VS Code configurée)

---

## Interface web

L'interface web (disponible sur `http://localhost:8080`) permet :

| Fonctionnalité | Description |
|---|---|
| **Nouveau run** | Saisir un objectif et lancer |
| **Logs en temps réel** | Streaming SSE des événements |
| **Historique** | Consulter les runs passés |
| **Arrêt** | Stopper le run en cours |

### États d'un run

```
INIT → PREFLIGHT → SNAPSHOT → PLAN → PREPARE_TASK
         ↓                              ↓
       erreur                      IMPLEMENT
                                       ↓
                                   VALIDATE ──→ REVIEW → COMMIT
                                       ↓
                                   ANALYZE → REPAIR → VALIDATE
                                       ↓ (max N loops)
                                   SKIP_TASK
                                       ↓
                                     DONE
```

---

## Comprendre les résultats

### Logs JSONL

Chaque run produit un fichier de log dans `logs/` :

```json
{"event": "plan_generated", "run_id": "abc123", "tasks": [...], "ts": "...", "sig": "hmac..."}
{"event": "task_completed", "task": "add_tests", "status": "ok", "ts": "...", "sig": "hmac..."}
```

Chaque entrée est **signée HMAC-SHA256** (non répudiable).

### Branches Git créées

L'orchestrateur travaille sur une branche `agent/<run-id>`. En cas de succès,
le commit est effectué sur cette branche. Vous pouvez ensuite faire une PR manuellement.

### Codes de sortie

| Code | Signification |
|---|---|
| `0` | Run terminé avec succès |
| `1` | Échec preflight (vérifier clés API, outils) |
| `2` | Toutes les tâches ont été ignorées (repair max atteint) |

---

## Commandes utiles

```bash
make bootstrap    # Installation complète
make install      # Installer les dépendances Python uniquement
make preflight    # Vérifier l'environnement sans lancer de run
make run          # Lancer un run orchestrateur
make start        # Démarrer le serveur API web
make stop         # Arrêter le serveur API web
make logs         # Afficher les logs en temps réel
make validate     # Lancer ruff + mypy + pytest
make clean        # Supprimer caches, logs, handoffs temporaires
make help         # Afficher toutes les commandes disponibles
```

---

## Questions fréquentes

**Q : L'orchestrateur s'arrête à PREFLIGHT avec "Codex CLI non trouvé".**
> Lancer : `npm install -g @openai/codex` puis relancer.

**Q : Rate limit error sur Claude.**
> Vérifier votre quota sur [console.anthropic.com](https://console.anthropic.com).
> Si `GEMINI_FALLBACK_ENABLED=true`, le fallback Gemini prendra le relais automatiquement.

**Q : Le repair loop atteint le maximum sans succès.**
> La tâche est ignorée (`skip_task`). Augmenter `ORCHESTRATOR_MAX_REPAIR_LOOPS`
> ou décomposer l'objectif en sous-tâches plus simples.

**Q : Puis-je pointer l'orchestrateur vers un autre dépôt ?**
> Oui : `DEFAULT_REPO_PATH=/chemin/vers/mon/projet` dans `.env`.

**Q : Les clés API sont-elles en sécurité ?**
> Elles sont stockées uniquement dans `.env` (exclu de Git par `.gitignore`).
> Gitleaks scanne chaque commit pour détecter toute fuite accidentelle.

**Q : Qu'est-ce que RTK ?**
> RTK (Runtime Token Kit) est un outil optionnel qui compresse les sorties bash
> avant qu'elles remontent aux LLM, réduisant la consommation de tokens de 60-90%.
> Il s'active automatiquement si installé (`brew install rtk`).
