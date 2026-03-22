# Procédures de réponse à incident — Multi-Agent Orchestrator

> Document opérationnel. À distribuer aux équipes SecOps et aux opérateurs du système.
> Réviser après chaque incident et à chaque évolution majeure de l'architecture.

---

## Table des matières

1. [Compromission d'une clé API LLM](#1-compromission-dune-clé-api-llm)
2. [Suspicion d'altération des logs HMAC](#2-suspicion-daltération-des-logs-hmac)
3. [Exploitation de prompt injection](#3-exploitation-de-prompt-injection)
4. [Compromission d'un composant externe](#4-compromission-dun-composant-externe)
5. [Fuite d'un token API d'authentification](#5-fuite-dun-token-api-dauthentification)
6. [Tentatives d'accès non autorisées répétées](#6-tentatives-daccès-non-autorisées-répétées)
7. [Matrice RACI incident](#7-matrice-raci-incident)

---

## 1. Compromission d'une clé API LLM

### Indicateurs d'alerte

- Facturation Anthropic / OpenAI anormalement élevée
- Gitleaks déclenche une alerte sur un commit
- Alerte SIEM sur pattern `sk-ant-` ou `sk-` dans les logs

### Actions immédiates (< 1 heure)

```bash
# 1. Révoquer immédiatement la clé compromise
# Anthropic : https://console.anthropic.com/settings/keys
# OpenAI    : https://platform.openai.com/api-keys
# Google    : https://aistudio.google.com/

# 2. Émettre une nouvelle clé

# 3. Mettre à jour .env sur tous les environnements
nano .env
# Remplacer la valeur de ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY

# 4. Relancer le service
make stop && make start

# 5. Vérifier qu'aucune clé ne subsiste dans les logs
grep -r "sk-ant-" logs/ orchestrator/handoffs/ || echo "OK — aucune clé dans les logs"
grep -r "sk-" logs/ --include="*.jsonl" | grep -v "sk-.*ICI\|sk-.*test\|sk-.*dummy"
```

### Investigation (< 24 heures)

- Identifier le vecteur de fuite (commit, log, erreur de copier-coller)
- Vérifier l'historique Git : `git log --all -S "sk-ant-" --source`
- Consulter les logs d'accès API chez le provider pour identifier les appels non autorisés
- Mettre à jour `.gitleaks.toml` si un nouveau pattern doit être ajouté à l'allowlist

### Rapport NIS2 (< 72 heures si OES/OSE)

Documenter : date/heure détection, vecteur de fuite, durée d'exposition estimée, actions correctives.

---

## 2. Suspicion d'altération des logs HMAC

### Indicateurs d'alerte

- Vérification de signature échoue
- Entrée de log sans champ `signature` ou `sig`
- Taille de fichier JSONL incohérente avec l'activité connue

### Vérification d'intégrité

```bash
# Vérifier toutes les signatures du journal de run
python3 - <<'EOF'
import hmac, hashlib, json
from pathlib import Path

key_file = Path(".orchestrator_signing_key")
if not key_file.exists():
    print("ERREUR : clé HMAC introuvable")
    exit(1)

key = key_file.read_bytes()
errors = 0

for log_file in Path("logs").glob("*.jsonl"):
    for i, line in enumerate(log_file.read_text().splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        sig_key = "signature" if "signature" in entry else "sig"
        if sig_key not in entry:
            print(f"MANQUANT : {log_file.name} ligne {i} — pas de signature")
            errors += 1
            continue
        sig = entry.pop(sig_key)
        payload = json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            print(f"ALTÉRÉ : {log_file.name} ligne {i}")
            errors += 1

if errors == 0:
    print(f"OK — toutes les signatures valides")
else:
    print(f"ALERTE : {errors} entrée(s) invalide(s) ou altérée(s)")
    exit(1)
EOF
```

### Actions si altération confirmée

1. **Isoler** les fichiers suspects (copier en read-only, ne pas modifier)
2. **Préserver** la clé HMAC actuelle (ne pas la supprimer — preuve forensique)
3. **Identifier** la fenêtre temporelle affectée (premier `ts` incohérent)
4. **Corréler** avec les logs d'audit HTTP (`logs/audit.jsonl`) pour identifier l'accès
5. **Notifier** le responsable sécurité et, si applicable, l'autorité compétente (NIS2 Art. 23)

### Rotation de la clé HMAC après incident

```bash
# ATTENTION : les anciens logs ne seront plus vérifiables avec la nouvelle clé.
# Archiver d'abord les logs existants.

cp -r logs/ logs-backup-$(date +%Y%m%d)/
rm .orchestrator_signing_key
# La nouvelle clé sera générée au prochain run
```

---

## 3. Exploitation de prompt injection

### Indicateurs d'alerte

- Commit sur une branche `agent/` contenant du code réseau inattendu (`requests`, `curl`, `socket`)
- Fichiers modifiés hors du périmètre `files_allowed` défini dans le handoff
- Requêtes HTTP vers des domaines externes dans les logs de validation
- Log de rejet 422 sur `/api/run` avec `security_event` dans `logs/audit.jsonl`

### Détection dans les logs d'audit

```bash
# Repérer les tentatives d'injection rejetées
grep '"security_event"' logs/audit.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('security_event') and e.get('status') in (401, 403, 422, 429):
        print(f'{e[\"ts\"]} | {e[\"security_event\"]} | IP={e[\"client_ip\"]} | path={e[\"path\"]}')
"
```

### Actions immédiates

```bash
# 1. Identifier le run suspect
tail -n 50 logs/audit.jsonl | grep '"status": 422'

# 2. Inspecter le diff produit par l'agent
git log --oneline agent/<run-id>
git diff agent/<run-id>^..agent/<run-id>

# 3. Si le code est malveillant : supprimer la branche
git branch -D agent/<run-id>

# 4. Vérifier qu'aucun fichier hors-scope n'a été modifié
git status
```

### Mesures correctives

- Renforcer les patterns `_INJECTION_PATTERNS` dans `api/security.py` si un nouveau vecteur est identifié
- Mettre à jour le fichier `.orchestrator-ignore` pour exclure les fichiers sensibles du snapshot
- Documenter le vecteur dans `SECURITY_DECISIONS.md`

---

## 4. Compromission d'un composant externe

### Composants critiques

| Composant | Vecteur de compromission | Détection |
|---|---|---|
| Claude CLI (`~/.local/bin/claude`) | Mise à jour malveillante | Hash binaire |
| Codex CLI (`~/.npm-global/bin/codex`) | npm compromise | `npm audit` |
| Image Docker base (`python:3.13-slim`) | CVE non patchée | Trivy / Grype CI |
| Dépendances Python (`requirements.txt`) | Supply chain | pip-audit |

### Procédure générale

```bash
# 1. Vérifier les hashes des binaires critiques
sha256sum ~/.local/bin/claude
sha256sum ~/.npm-global/bin/codex

# 2. Auditer les dépendances Python
pip-audit -r requirements.txt

# 3. Auditer les dépendances npm
npm audit --prefix ~/.npm-global

# 4. Reconstruire l'image Docker depuis zéro
docker build --no-cache -t multi-agent-orchestrator .

# 5. Relancer les scans CVE
# (voir CI/CD — jobs trivy-image et grype-image)
```

### Si un composant est confirmé compromis

1. **Arrêter** tous les runs actifs : `make stop`
2. **Isoler** l'environnement (bloquer le réseau sortant si possible)
3. **Downgrader** vers la dernière version connue saine
4. **Vérifier** les commits produits depuis la compromission
5. **Notifier** (NIS2 Art. 23 si applicable)

---

## 5. Fuite d'un token API d'authentification

### Tokens concernés

- `API_TOKEN_ADMIN` — accès total
- `API_TOKEN_OPERATOR` — lancement de runs
- `API_TOKEN_READER` — lecture seule

### Actions immédiates

```bash
# 1. Générer de nouveaux tokens
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# (répéter pour chaque rôle)

# 2. Mettre à jour .env
nano .env
# Remplacer API_TOKEN_ADMIN, API_TOKEN_OPERATOR, API_TOKEN_READER

# 3. Redémarrer le service
make stop && make start

# 4. Invalider tous les tokens en circulation
# (distribuer les nouveaux tokens aux utilisateurs légitimes)
```

### Investigation

```bash
# Chercher les utilisations du token compromis dans les logs d'audit
# (les tokens ne sont pas loggés, mais les IP/rôles oui)
grep '"role": "admin"' logs/audit.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print(f'{e[\"ts\"]} | IP={e[\"client_ip\"]} | {e[\"method\"]} {e[\"path\"]}')
" | sort
```

---

## 6. Tentatives d'accès non autorisées répétées

### Détection automatique

Les événements d'échec d'authentification sont loggés dans `logs/audit.jsonl` avec :
- `"security_event": "auth_failure"` pour 401
- `"security_event": "authz_failure"` pour 403
- `"security_event": "rate_limit_exceeded"` pour 429

### Script d'analyse

```bash
python3 - <<'EOF'
import json
from collections import Counter
from pathlib import Path

entries = []
audit = Path("logs/audit.jsonl")
if not audit.exists():
    print("Aucun log d'audit trouvé")
    exit(0)

for line in audit.read_text().splitlines():
    if not line.strip():
        continue
    e = json.loads(line)
    if e.get("security_event"):
        entries.append(e)

# Top IP par événement de sécurité
ip_counts = Counter(e["client_ip"] for e in entries)
print("=== Top IP avec événements de sécurité ===")
for ip, count in ip_counts.most_common(10):
    print(f"  {count:4d}x  {ip}")

# Chronologie
print(f"\n=== {len(entries)} événements de sécurité au total ===")
for e in entries[-20:]:
    print(f"  {e['ts']} | {e['security_event']} | IP={e['client_ip']} | {e['method']} {e['path']}")
EOF
```

### Actions si brute-force détecté

1. **Bloquer l'IP** au niveau réseau (pare-feu, nginx `deny`)
2. **Vérifier** si un token a été compromis (voir section 5)
3. **Renforcer le rate limiting** : diminuer `RATE_LIMIT_RUN` et `RATE_LIMIT_DEFAULT` dans `.env`

---

## 7. Matrice RACI incident

| Action | Responsable | Approuvé par | Consulté | Informé |
|---|---|---|---|---|
| Revocation clé API | Opérateur | RSSI | Développeur | Direction |
| Rotation token HMAC | Opérateur | RSSI | — | Audit |
| Suppression branche agent compromise | Développeur | Lead | RSSI | — |
| Notification CSIRT / NIS2 | RSSI | Direction | Juridique | — |
| Mise à jour patterns injection | Développeur | Lead Sécu | — | RSSI |
| Blocage IP | Opérateur réseau | RSSI | — | — |

---

*Dernière révision : 2026-03-21. Réviser tous les 6 mois ou après tout incident.*
