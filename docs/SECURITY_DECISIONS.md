# Architecture Decision Records — Sécurité

> Trace des arbitrages et décisions d'architecture de sécurité.
> Référence pour les revues de code et les audits.

---

## ADR-001 : Authentification par Bearer token statique (pas JWT)

**Date :** 2026-03-21
**Statut :** Accepté

### Contexte
L'API nécessite une authentification. Les options évaluées :
- JWT signé (RS256 / HS256)
- Bearer token statique (clé secrète fixe par rôle)
- mTLS (certificats client)

### Décision
Bearer token statique, un par rôle (admin / operator / reader), stocké dans `.env`.

### Justification
- Simplicité d'implémentation et de rotation (modifier `.env`, redémarrer)
- Pas de dépendance à un serveur d'identité (OIDC, Keycloak)
- Comparaison en temps constant via `hmac.compare_digest` (résistant au timing attack)
- Adapté à un déploiement single-tenant

### Trade-offs
- Pas de révocation granulaire par session (rotation = nouveau token pour tous)
- Pas d'expiration automatique (à implémenter si besoin de rotation forcée)

### Migration future
Si besoin de multi-tenant ou fédération d'identité : migrer vers JWT (python-jose)
ou OAuth2 PKCE. La couche `api/security.py` est conçue pour être remplacée
sans modifier `server.py`.

---

## ADR-002 : Rate limiting en mémoire (pas Redis)

**Date :** 2026-03-21
**Statut :** Accepté

### Contexte
Besoin de rate limiting pour protéger l'API contre l'abus et le DoS.

### Décision
`slowapi` avec stockage en mémoire (in-process). Pas de Redis.

### Justification
- L'orchestrateur est single-instance (un seul process actif à la fois)
- Redis introduirait une dépendance externe et de la complexité opérationnelle
- En mémoire suffit pour le cas d'usage actuel

### Trade-offs
- Les compteurs sont perdus au redémarrage du service
- Inefficace si déployé derrière plusieurs instances (load balancer) — à ce stade non prévu

### Migration future
Si déploiement multi-instance : passer à `slowapi` avec backend Redis
ou utiliser le rate limiting au niveau du reverse proxy (nginx, Traefik).

---

## ADR-003 : SecretStr Pydantic pour les clés API

**Date :** 2026-03-21
**Statut :** Accepté

### Contexte
Les clés API (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) étaient
stockées en `str` dans `Settings`, ce qui les exposait dans les `repr()` / logs Pydantic.

### Décision
Migration vers `SecretStr` de Pydantic pour tous les champs secrets.
Exposition de propriétés helper (`anthropic_api_key_value`, etc.) pour les workers
qui ont besoin de la valeur brute.

### Justification
- `SecretStr.__repr__` retourne `'**********'` — protège contre les fuites dans les logs
- `str(SecretStr("sk-..."))` retourne `'**********'` — protège contre les print accidentels
- Standard Pydantic reconnu

### Impact sur le code
- `gemini_worker.py` : `cfg.gemini_api_key` → `cfg.gemini_api_key_value`
- `codex_worker.py` : `cfg.openai_api_key` → `cfg.openai_api_key_value`
- `claude_worker.py` : non affecté (utilise `os.environ` via subprocess)

---

## ADR-004 : Validation anti-injection au niveau API (pas au niveau LLM)

**Date :** 2026-03-21
**Statut :** Accepté

### Contexte
Le champ `goal` est transmis directement aux LLM. Un attaquant pourrait y injecter
des instructions système pour détourner le comportement de l'orchestrateur.

### Décision
Validation par regex côté API (`api/security.py`) avant toute transmission au LLM.
Patterns ciblés sur la manipulation d'instructions système, pas les termes techniques.

### Justification
- Défense en profondeur : rejeter au plus tôt (API) plutôt que d'espérer que le LLM résiste
- Patterns conservateurs : bloquer uniquement les intentions manifestes d'injection,
  pas les termes techniques légitimes (`subprocess`, `exec`, `eval` dans un contexte de code)
- Facilement auditable et testable (tests unitaires dédiés)

### Limites
- Pas de protection à 100% contre les injections sophistiquées
- Les LLM modernes ont leur propre résistance aux injections (Claude notamment)
- La validation API est un complément, pas un remplacement de la sécurité LLM

### Patterns retenus et justification

| Pattern | Justification |
|---|---|
| `ignore.*previous.*instructions` | Injection classique, jamais légitime |
| `forget.*previous.*rules` | Idem |
| `you are now [non-engineer]` | Changement de persona système |
| `act as [non-engineer]` | Idem |
| `exfiltrat*` | Intention d'exfiltration explicite |
| `send * to` | Exfiltration de données |
| `<system>` | Injection de balise système |
| `[INST]` | Injection format LLaMA |

---

## ADR-005 : Audit log HMAC séparé (`logs/audit.jsonl`)

**Date :** 2026-03-21
**Statut :** Accepté

### Contexte
Les logs de run (`logs/<run_id>.jsonl`) tracent les événements applicatifs.
Il manquait une traçabilité des accès HTTP/API (qui appelle quoi, quand).

### Décision
Middleware FastAPI qui écrit dans `logs/audit.jsonl` chaque accès HTTP,
signé avec la même clé HMAC que les logs de run.

### Ce qui est loggé
- Timestamp, méthode HTTP, path, statut HTTP
- IP client
- Rôle de l'appelant (pas la valeur du token)
- Durée de traitement
- `security_event` si 401/403/429

### Ce qui n'est PAS loggé
- Valeur du token Bearer (jamais)
- Corps de la requête (pourrait contenir des données sensibles)
- Valeurs des clés API

### Justification NIS2
Art. 21.2.j — Contrôle d'accès : la journalisation des accès est une exigence
fondamentale pour la détection d'incidents et les investigations post-incident.

---

## ADR-006 : `AUTH_ENABLED=false` pour le développement local

**Date :** 2026-03-21
**Statut :** Accepté avec conditions

### Contexte
En développement local, configurer les tokens pour chaque test est fastidieux.

### Décision
Variable `AUTH_ENABLED` (défaut `true`) permettant de désactiver l'auth localement.

### Conditions strictes
- `AUTH_ENABLED=false` ne doit **jamais** être utilisé en production
- Le mode bypass retourne `Role.admin` (accès total) — intentionnel pour le dev
- Documenter cette restriction dans `.env.example` et les guides de déploiement

### Alternative considérée
Tokens de développement pré-définis — rejeté car risque de tokens hardcodés
qui se retrouvent en production.

---

## ADR-007 : SBOM en format CycloneDX (deux niveaux)

**Date :** 2026-03-21
**Statut :** Accepté

### Décision
Génération de deux SBOM :
1. `sbom-python.cyclonedx.json` — dépendances Python (`cyclonedx-bom`)
2. `sbom-image.cyclonedx.json` — image Docker complète (`syft`)

### Justification
- CycloneDX est le standard recommandé par l'ANSSI et ENISA pour NIS2
- Le SBOM image capture aussi les packages OS (plus complet)
- Les deux SBOM sont archivés 90 jours comme artefacts CI

### Utilisation
- Ingestion dans un outil de gestion des vulnérabilités (DependencyTrack)
- Fourni aux clients / auditeurs comme preuve de traçabilité de la chaîne d'approvisionnement

---

## Risques résiduels documentés

| ID | Risque | Niveau | Décision |
|---|---|---|---|
| R-001 | JWT non implémenté → pas d'expiration de session | Moyen | Acceptable (single-tenant) |
| R-002 | Rate limit en mémoire → non persisté | Faible | Acceptable (single-instance) |
| R-003 | API HTTP (pas HTTPS nativement) | Élevé | **Mitigation requise** : reverse proxy TLS |
| R-004 | Chiffrement au repos non implémenté | Moyen | Acceptable court terme, LUKS recommandé |
| R-005 | Injection sophistiquée non détectable par regex | Moyen | Acceptable (défense en profondeur) |
| R-006 | Clé HMAC sur disque local | Moyen | KMS recommandé en production |
| R-007 | `AUTH_ENABLED=false` risque en prod | Élevé | Contrôle procédural (formation, checklist déploiement) |

---

*Maintenu par l'équipe sécurité. Mise à jour obligatoire lors de tout changement d'architecture de sécurité.*
