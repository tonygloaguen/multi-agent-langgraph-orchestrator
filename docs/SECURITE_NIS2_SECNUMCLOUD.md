# Multi-Agent Orchestrator — Sécurité, NIS2 & SecNumCloud

> Analyse des mécanismes de sécurité, cartographie des exigences NIS2 (Directive EU 2022/2555)
> et évaluation de la trajectoire vers la qualification SecNumCloud (ANSSI).

---

## Table des matières

1. [Mécanismes de sécurité implémentés](#mécanismes-de-sécurité-implémentés)
2. [Cartographie NIS2](#cartographie-nis2)
3. [Trajectoire SecNumCloud](#trajectoire-secnumcloud)
4. [Analyse des risques (threat model)](#analyse-des-risques-threat-model)
5. [Matrice de conformité consolidée](#matrice-de-conformité-consolidée)

---

## Mécanismes de sécurité implémentés

### 1. Gestion des secrets — Isolation totale (SecretStr)

**Mécanisme :** Les clés API et tokens d'authentification sont exclusivement lus
depuis `.env` via Pydantic-Settings avec `SecretStr`. Aucune valeur sensible n'est
hardcodée, passée en argument CLI, ni écrite dans les logs.

```python
# orchestrator/config.py
class Settings(BaseSettings):
    anthropic_api_key: SecretStr
    openai_api_key: SecretStr
    gemini_api_key: SecretStr | None = None
    # Tokens d'authentification API
    api_token_admin: SecretStr | None = None
    api_token_operator: SecretStr | None = None
    api_token_reader: SecretStr | None = None
    # Feature flags
    auth_enabled: bool = True
    cors_allowed_origins: str = "http://localhost:3000"
    rate_limit_run: str = "5/minute"
    rate_limit_default: str = "60/minute"
```

**Garanties :**
- `.env` exclu de Git (`.gitignore`)
- `SecretStr` : jamais affiché par `str()` ou `repr()` — protège dans les tracebacks
- Les workers reçoivent la valeur via `.get_secret_value()` uniquement au moment de l'invocation
- Les tokens Bearer ne sont **jamais** journalisés ni exposés dans les réponses d'erreur

---

### 2. Authentification forte sur l'API — Bearer HMAC timing-safe

**Mécanisme :** Tous les endpoints sensibles exigent un token Bearer.
La comparaison utilise `hmac.compare_digest` (timing-safe, résistant aux
timing attacks permettant la devinette de tokens caractère par caractère).

```python
# api/security.py
def _verify_token(provided: str, expected: SecretStr) -> bool:
    return hmac.compare_digest(
        provided.encode(),
        expected.get_secret_value().encode()
    )
```

Réponse en cas d'échec : HTTP 401 avec message générique, sans indication
sur la nature de l'erreur. L'événement est journalisé dans `audit.jsonl`
avec `security_event: true`.

---

### 3. Contrôle d'accès / RBAC — 3 rôles

**Mécanisme :** Trois rôles avec périmètres d'action stricts, enforced par
`Depends(require_roles(...))` sur chaque endpoint FastAPI.

| Rôle | Token source | Actions |
|---|---|---|
| `admin` | `API_TOKEN_ADMIN` | Tout (run, stop, status, history, logs) |
| `operator` | `API_TOKEN_OPERATOR` | Lancer run, consulter status et logs |
| `reader` | `API_TOKEN_READER` | Consulter status et history uniquement |

Violation RBAC → HTTP 403 + `security_event` dans `logs/audit.jsonl`.

---

### 4. Rate limiting — slowapi par IP

**Mécanisme :** Limitation configurable par endpoint, appliquée par adresse IP.

```dotenv
RATE_LIMIT_RUN=5/minute      # POST /api/run (protection contre abus)
RATE_LIMIT_DEFAULT=60/minute # Autres endpoints
```

Dépassement → HTTP 429 + `security_event` dans audit log.

> **Risque résiduel :** Le backend est en mémoire — réinitialisé au restart.
> Pour un déploiement multi-instance ou haute disponibilité, utiliser Redis
> comme backend slowapi (voir `docs/SECURITY_DECISIONS.md`, ADR-02).

---

### 5. Validation des entrées — anti-injection et sanitisation

**Mécanisme :** Le champ `goal` est validé avant tout traitement LLM.
12 patterns regex bloquent les tentatives d'injection connues :

```python
INJECTION_PATTERNS = [
    r"ignore\s+(previous\s+)?instructions",
    r"disregard\s+(previous\s+)?",
    r"exfiltrate",
    r"<s>|</s>|<\|im_start\|>|<\|im_end\|>",
    r"\[INST\]|\[/INST\]",
    r"system\s*prompt",
    r"you\s+are\s+now",
    r"act\s+as\s+(if\s+you\s+(are|were)|a)",
    r"jailbreak",
    r"bypass\s+(safety|filter|restriction)",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"</?system>",
]
```

- Longueur max : 2000 caractères
- `repo_path` : blocage de `;`, `&`, `|`, `` ` ``, `$`, `>`, `<`, `\n`, `\r`
- Payload rejeté → HTTP 422 + `security_event`

---

### 6. Headers de sécurité HTTP

**Mécanisme :** Middleware FastAPI injectant des headers sur toutes les réponses.

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'
Server: (supprimé — pas de fingerprinting)
```

CORS restreint à `CORS_ALLOWED_ORIGINS` — plus de wildcard `*`.

---

### 7. Journal d'audit HTTP — traçabilité des accès API

**Mécanisme :** Chaque requête API produit une entrée signée HMAC dans
`logs/audit.jsonl`, distincte des logs d'orchestration.

```json
{
  "ts": "2026-03-22T10:15:30Z",
  "ip": "192.168.1.10",
  "role": "operator",
  "method": "POST",
  "path": "/api/run",
  "status": 200,
  "duration_ms": 42,
  "security_event": false,
  "sig": "hmac-sha256:d4e5f6..."
}
```

Les événements de sécurité (401, 403, 422, 429) sont explicitement marqués
`security_event: true` pour faciliter l'ingestion SIEM et le filtrage d'alertes.

---

### 8. Journal d'audit orchestration — HMAC-SHA256

**Mécanisme :** Chaque événement de l'orchestrateur est signé
cryptographiquement avant écriture dans `logs/<run_id>.jsonl`.

```python
def _sign_event(event: dict) -> str:
    key = _load_signing_key()
    payload = json.dumps(event, sort_keys=True).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()
```

**Propriétés garanties :**
- **Intégrité** : toute modification d'une entrée invalide sa signature
- **Non-répudiation** : la clé locale prouve l'origine système
- **Ordering** : champ `ts` ISO 8601 UTC pour reconstruction chronologique

**Vérification :**
```bash
python3 -c "
import hmac, hashlib, json
key = open('.orchestrator_signing_key','rb').read()
ok = 0
for i, line in enumerate(open('logs/run.jsonl'), 1):
    e = json.loads(line)
    sig = e.pop('sig')
    expected = hmac.new(key, json.dumps(e,sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert sig == expected, f'Ligne {i} ALTÉRÉE'
    ok += 1
print(f'{ok} entrées vérifiées — journal intègre')
"
```

---

### 9. Détection de fuites de secrets — Gitleaks

**Double filet :**
- Local : hook pre-commit bloque avant le commit
- CI/CD : job `gitleaks` bloque le merge

Patterns couverts : `sk-ant-*` (Anthropic), `sk-*` (OpenAI), Google API keys,
clés SSH, certificats, tokens JWT, Bearer tokens.

---

### 10. Scan de vulnérabilités — Trivy + Grype + pip-audit

```yaml
# ci.yml — security gates actifs
trivy:   exit-code 1 sur CRITICAL (image Docker)
grype:   --only-fixed --fail-on high (image Docker)
pip-audit: échec si CVE fixable sur dépendances Python
bandit:  medium+ SAST Python (Bandit)
```

---

### 11. SBOM — Software Bill of Materials

Deux SBOM générés et archivés 90 jours comme artefacts CI :
- **CycloneDX JSON** : dépendances Python (pip)
- **syft CycloneDX JSON** : image Docker complète (OS + pip)

```bash
# Générer manuellement
cyclonedx-py -e --format json -o sbom-python.json
syft multi-agent-orchestrator:latest -o cyclonedx-json > sbom-image.json
```

---

### 12. Contrôle du scope d'exécution — files_allowed

Chaque tâche définit `files_allowed`. Codex ne peut modifier que ces fichiers.
Claude vérifie la conformité du diff lors de la revue.

---

### 13. Détection de régression automatique

Si un repair Codex augmente le nombre d'erreurs (ruff + mypy + pytest) :
rollback automatique via `git checkout -- .`.

---

### 14. Validation statique — Ruff + Mypy + Bandit

| Outil | Rôle | Exécution |
|---|---|---|
| Ruff | Lint PEP8 + règles sécurité (eval, exec...) | pre-commit + CI |
| Mypy strict | Typage statique | pre-commit + CI |
| Bandit | SAST Python (injections, crypto faible...) | CI uniquement |

---

### 15. Tests de sécurité dédiés

```
tests/test_api_security.py      (45 tests)
  - tokens valides/invalides
  - timing-safe (comparaison HMAC)
  - RBAC par rôle et endpoint
  - comportement rate limit

tests/test_input_validation.py  (45 tests)
  - 12 patterns d'injection
  - cas légitimes non bloqués
  - caractères shell dangereux
  - payloads surdimensionnés
  - encodages / JSON malformé
```

96/96 tests passent. Ruff clean. Mypy strict OK.

---

## Cartographie NIS2

La Directive NIS2 (EU 2022/2555), transposée en droit français (2024),
impose des mesures de cybersécurité aux entités essentielles et importantes.

### Article 21 — Mesures de gestion des risques

| Exigence NIS2 (Art. 21) | Mécanisme implémenté | Statut | Gap résiduel |
|---|---|---|---|
| **21.2.a** Politiques sécurité SI | `CLAUDE.md`, `SECURITY_DECISIONS.md` (7 ADR), pre-commit | Partiel | Politique formelle signée manquante |
| **21.2.b** Gestion des incidents | HMAC journal + audit log + `INCIDENT_RESPONSE.md` | Partiel | Connexion SIEM non automatisée |
| **21.2.c** Continuité activité | Fallback Gemini si Claude KO | Partiel | PCA/PRA non documenté |
| **21.2.d** Sécurité chaîne d'approvisionnement | Trivy + Grype + pip-audit + SBOM CycloneDX | **Oui** | Signature image (cosign) absente |
| **21.2.e** Sécurité acquisition/dev/maintenance | Ruff, Mypy, Bandit, Gitleaks, pre-commit | **Oui** | — |
| **21.2.f** Évaluation des risques | Threat model (ce document) + SECURITY_DECISIONS.md | Partiel | EBIOS RM formelle manquante |
| **21.2.g** Pratiques hygiène cyber | `.gitignore`, `SecretStr`, rotation clés documentée | **Oui** | Formation utilisateurs manquante |
| **21.2.h** Cryptographie | HMAC-SHA256, SecretStr, timing-safe auth | Partiel | TLS non natif (reverse proxy requis) |
| **21.2.i** Sécurité RH | Séparation Claude/Codex/Gemini | **Oui** | — |
| **21.2.j** Contrôle d'accès | Bearer auth + RBAC 3 rôles + files_allowed | **Oui** | MFA absent (dépend IdP) |
| **21.2.k** Gestion des actifs | JSONL signés + SBOM archivé | Partiel | Inventaire actifs formel absent |

### Article 23 — Notification des incidents

| Exigence | État actuel | Action requise |
|---|---|---|
| Notification < 24h (alerte précoce) | `audit.jsonl` security_events filtrables | Connecter à SIEM / alerting |
| Notification < 72h (rapport initial) | `INCIDENT_RESPONSE.md` + scripts bash | Procédure de notification formalisée |
| Rapport final (1 mois) | Manuel (consultation logs) | Template de rapport à créer |

### Points forts NIS2 (état actuel)

- **Authentification forte** : Bearer timing-safe, 3 rôles RBAC
- **Traçabilité complète** : audit log HTTP + événements orchestration, tous signés HMAC
- **Supply chain** : SBOM CycloneDX + Trivy + Grype + pip-audit en CI
- **Détection injection** : 12 patterns regex sur les entrées libres
- **Incident response** : `INCIDENT_RESPONSE.md` avec 6 procédures + scripts bash + RACI
- **Décisions traçables** : `SECURITY_DECISIONS.md` avec 7 ADR documentés

### Gaps NIS2 résiduels prioritaires

1. **TLS** : API en HTTP pur ; reverse proxy TLS obligatoire avant exposition externe
2. **SIEM** : les `security_event` de `audit.jsonl` ne déclenchent pas encore d'alertes automatiques
3. **Notification incidents** : procédure formelle NIS2 (CERT/CSIRT) à rédiger
4. **EBIOS RM** : analyse de risques formelle (ce document est un threat model, pas un EBIOS)
5. **PCA/PRA** : plan de continuité non documenté

---

## Trajectoire SecNumCloud

> **Note** : Le Multi-Agent Orchestrator est un outil de développement, pas une
> infrastructure Cloud à qualifier directement. S'il est déployé dans un contexte
> sensible (administration, OIV/OSE), il doit s'insérer dans une infrastructure qualifiée.

### Exigences SecNumCloud applicables

#### Chapitre 5 — Protection des données

| Exigence | État | Détail |
|---|---|---|
| **5.1** Chiffrement données au repos | Non natif | Logs JSONL en clair — LUKS/VeraCrypt recommandé |
| **5.2** Chiffrement données en transit | Partiel | HTTP en interne ; TLS requis si exposition externe |
| **5.3** Gestion des clés | Partiel | Clé HMAC locale (`chmod 0o600`) — HSM/KMS en production |
| **5.4** Minimisation données | Oui | Seules les données nécessaires au run sont traitées |

#### Chapitre 6 — Contrôle d'accès

| Exigence | État | Détail |
|---|---|---|
| **6.1** Authentification forte | **Oui** | Bearer HMAC timing-safe, 3 tokens distincts par rôle |
| **6.2** Principe moindre privilège | **Oui** | RBAC enforced + files_allowed par tâche |
| **6.3** Journalisation des accès | **Oui** | `audit.jsonl` signé HMAC : IP, rôle, path, statut, durée |
| **6.4** Séparation des privilèges | **Oui** | Chaque agent a un rôle distinct et limité |

#### Chapitre 7 — Gestion des incidents

| Exigence | État | Détail |
|---|---|---|
| **7.1** Détection | Partiel | Logs HMAC + security_events ; SIEM non intégré |
| **7.2** Réponse aux incidents | **Oui** | `INCIDENT_RESPONSE.md` : 6 procédures + scripts + RACI |
| **7.3** Forensique | Partiel | Logs horodatés et signés ; image mémoire non prévue |

#### Chapitre 9 — Sécurité des développements

| Exigence | État | Détail |
|---|---|---|
| **9.1** Analyse statique | **Oui** | Ruff + Mypy + Bandit |
| **9.2** Tests de sécurité | **Oui** | 90 tests dédiés sécurité (auth, RBAC, injection) |
| **9.3** Gestion des dépendances | **Oui** | Trivy + Grype + pip-audit + SBOM CycloneDX |
| **9.4** Code review | **Oui** | Claude `review_conformance()` + pre-commit |
| **9.5** Secrets dans le code | **Oui** | Gitleaks (pre-commit + CI) + SecretStr |

### Roadmap SecNumCloud

```
Niveau 1 — Fondations (complété)
├── ✅ Authentification API Bearer (timing-safe)
├── ✅ RBAC 3 rôles
├── ✅ Rate limiting par IP
├── ✅ Validation anti-injection entrées
├── ✅ Headers sécurité HTTP
├── ✅ Audit log HTTP signé HMAC
├── ✅ SBOM CycloneDX (Python + image)
├── ✅ SAST Bandit + pip-audit en CI
├── ✅ INCIDENT_RESPONSE.md + SECURITY_DECISIONS.md

Niveau 2 — Renforcement (à faire, 3-6 mois)
├── Reverse proxy TLS 1.3 (nginx/caddy)
├── KMS pour la clé HMAC (HashiCorp Vault, AWS KMS)
├── Connexion logs SIEM (OpenSearch, Wazuh) sur security_events
├── Alerting automatique (tentatives auth, violations RBAC)
├── Chiffrement logs au repos (LUKS sur volume logs/)
├── EBIOS RM formelle
└── PCA/PRA documenté et testé

Niveau 3 — Qualification (si applicable)
├── Hébergement sur infrastructure qualifiée SecNumCloud
│   (OVHcloud, Outscale, S3NS)
├── Audit PASSI (prestataire qualifié ANSSI)
├── Procédure notification incidents NIS2 (CERT/CSIRT)
├── Signature image Docker (cosign / Sigstore)
└── mTLS pour exposition API en production
```

---

## Analyse des risques (threat model)

### Surfaces d'attaque identifiées

| Surface | Vecteur | Risque | Mitigation actuelle | Résidu |
|---|---|---|---|---|
| **API FastAPI** | Accès non authentifié | Critique | ✅ Bearer auth + RBAC | TLS absent |
| **Tokens Bearer** | Vol ou brute-force | Élevé | ✅ timing-safe, SecretStr, jamais loggé | Pas d'expiration (pas de JWT) |
| **Champ `goal`** | Prompt injection | Élevé | ✅ 12 patterns regex + longueur max | Injections sophistiquées non couvertes |
| **Fichier `.env`** | Lecture par malware local | Élevé | ✅ `.gitignore`, `SecretStr` | chmod 0o600 recommandé |
| **Clé HMAC** | Vol → falsification de logs | Élevé | ✅ `chmod 0o600` | KMS manquant en prod |
| **Codex bypass** | Exécution de code arbitraire | Élevé | ✅ `files_allowed` scope enforcement | Dépendance à la revue Claude |
| **Rate limit** | DoS par épuisement quota API | Moyen | ✅ slowapi par IP | Reset au restart (mémoire) |
| **Dépendances Python** | CVE dans requirements | Moyen | ✅ Trivy + Grype + pip-audit | Veille continue nécessaire |
| **Logs JSONL** | Exfiltration de données | Moyen | ✅ HMAC détecte altération | Chiffrement au repos absent |
| **Commits Git** | Code malveillant commité | Faible | ✅ Gitleaks + Ruff + Mypy + review | — |

### Scénarios de risque critiques

#### Scénario 1 : Compromission token Bearer admin

```
Vecteur    : Fuite .env ou interception réseau (absence TLS)
Détection  : Accès anormaux dans audit.jsonl (IP inconnue, horaire inhabituel)
Impact     : Accès complet à l'API, lancement de runs arbitraires
Réponse    : Voir INCIDENT_RESPONSE.md §1 — Compromission clé API
             → Rotation immédiate API_TOKEN_ADMIN dans .env
             → Redémarrage service
             → Revue audit.jsonl sur les 24h précédentes
```

#### Scénario 2 : Prompt injection sophistiquée

```
Vecteur    : goal contournant les 12 patterns regex (obfuscation Unicode, encodage)
Détection  : review_conformance() peut détecter les appels réseau hors scope
Impact     : Potentiel exfiltration si Codex génère du code réseau non détecté
Mitigation : Valider goal côté LLM (system prompt hardened)
             Monitoring des diffs Git produits par les runs
```

#### Scénario 3 : Altération des logs d'audit

```
Vecteur    : Accès filesystem + modification JSONL
Détection  : Signature HMAC invalide lors de la vérification
Impact     : Non-conformité audit NIS2, impossibilité de prouver l'intégrité
Réponse    : Voir INCIDENT_RESPONSE.md §2 — Suspicion de falsification de logs
Mitigation : Logs en destination write-once (S3 Object Lock, WORM)
```

#### Scénario 4 : Compromission d'une dépendance (supply chain)

```
Vecteur    : CVE introduite dans une mise à jour pip
Détection  : pip-audit en CI, Trivy sur image
Impact     : RCE potentielle dans le contexte orchestrateur
Réponse    : Voir INCIDENT_RESPONSE.md §3 — Compromission composant externe
             → Pinning de la dépendance à la version saine
             → Rebuild image + redéploiement
             → Revue SBOM pour identifier les dépendants
```

---

## Matrice de conformité consolidée

| Domaine | Exigence | Implémenté | Niveau | Action restante |
|---|---|---|---|---|
| **Accès** | Auth API Bearer | ✅ Oui | Fort | — |
| **Accès** | RBAC 3 rôles | ✅ Oui | Fort | — |
| **Accès** | Rate limiting par IP | ✅ Oui | Moyen | Redis si multi-instance |
| **Accès** | MFA | Non | NIS2 requis | Dépend de l'IdP |
| **Secrets** | SecretStr toutes les clés | ✅ Oui | Fort | — |
| **Secrets** | Détection fuites (local + CI) | ✅ Oui | Fort | — |
| **Secrets** | KMS / rotation automatisée | Non | SecNumCloud | HashiCorp Vault |
| **Entrées** | Validation anti-injection | ✅ Oui | Fort | Injections Unicode avancées |
| **Entrées** | Sanitisation repo_path | ✅ Oui | Fort | — |
| **Audit** | Journal orchestration HMAC | ✅ Oui | Fort | — |
| **Audit** | Journal accès HTTP HMAC | ✅ Oui | Fort | — |
| **Audit** | Security events filtrables | ✅ Oui | Fort | Connexion SIEM |
| **Audit** | Logs write-once | Non | Moyen | S3 Object Lock / WORM |
| **Transit** | TLS | Non natif | Critique | Reverse proxy nginx/caddy |
| **Repos** | Chiffrement FS logs | Non | Moyen | LUKS sur volume logs/ |
| **Repos** | KMS applicatif | Non | SecNumCloud | HashiCorp Vault |
| **Dev** | Lint statique (Ruff) | ✅ Oui | Fort | — |
| **Dev** | Typage statique (Mypy) | ✅ Oui | Fort | — |
| **Dev** | SAST Bandit | ✅ Oui | Fort | — |
| **Dev** | Tests sécurité dédiés (90) | ✅ Oui | Fort | — |
| **Dev** | DAST | Non | Moyen | OWASP ZAP en CI |
| **Chaîne** | Scan CVE images (Trivy+Grype) | ✅ Oui | Fort | — |
| **Chaîne** | Audit dépendances Python (pip-audit) | ✅ Oui | Fort | — |
| **Chaîne** | SBOM CycloneDX (Python + image) | ✅ Oui | Fort | — |
| **Chaîne** | Signature image (cosign) | Non | SecNumCloud | Sigstore / cosign |
| **Résil.** | Fallback LLM (Gemini) | ✅ Oui | Moyen | — |
| **Résil.** | PCA/PRA | Non | NIS2 requis | Documenter |
| **IR** | INCIDENT_RESPONSE.md + scripts | ✅ Oui | Fort | Connexion SIEM |
| **IR** | Notification NIS2 (CERT) | Non | NIS2 requis | Procédure formelle |
| **Risques** | Threat model | ✅ Oui | Moyen | EBIOS RM formelle |
| **Risques** | SECURITY_DECISIONS.md (7 ADR) | ✅ Oui | Fort | — |
| **Risques** | Analyse risques LLM/prompt | ✅ Partiel | Moyen | Injections sophistiquées |

### Légende niveaux

| Niveau | Signification |
|---|---|
| **Fort** | Contrôle robuste en place |
| **Moyen** | Contrôle partiel ou améliorable |
| **Critique** | Absence bloquante pour conformité |
| **NIS2 requis** | Exigence formelle NIS2 non couverte |
| **SecNumCloud** | Requis pour qualification ANSSI |

---

*Document mis à jour le 2026-03-22 suite au durcissement sécurité Phase 1–4
(auth Bearer, RBAC, rate limiting, anti-injection, audit log HMAC, SBOM, CI gates,
INCIDENT_RESPONSE.md, SECURITY_DECISIONS.md). Réviser à chaque évolution majeure
de l'architecture ou de la réglementation applicable.*
