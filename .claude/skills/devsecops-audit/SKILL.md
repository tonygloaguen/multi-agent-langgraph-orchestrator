---
name: devsecops-audit
description: >
  Audit CI/CD, GitHub Actions, supply chain.
  Utiliser pour : vérifier les versions d'actions, détecter curl|bash,
  auditer les permissions GITHUB_TOKEN, review Dockerfile, Trivy/Checkov/Gitleaks.
allowed: Read, Bash
---

## Vérifications critiques

### Versions épinglées
```bash
grep -rn "uses:.*@\(main\|master\|latest\)" .github/
```
Toute action sur @main/@master/@latest = CRITIQUE

### curl|bash
```bash
grep -rn "curl.*|.*sh\|wget.*|.*bash" .github/
```

### pull_request_target + secrets = CRITIQUE
Vecteur d'attaque Trivy — vérifier systématiquement

### Niveaux de criticité
- 🔴 CRITIQUE — corriger avant le prochain push
- 🟡 WARN — corriger dans la semaine  
- 🔵 INFO — bonne pratique à adopter
