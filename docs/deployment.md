# Déploiement — résumé

## Une seule fois
1. bash scripts/bootstrap.sh
2. code .  (ouvrir VS Code)
3. Cliquer "Allow" sur la notification

## À chaque fois
1. Ouvrir VS Code sur ce dossier → orchestrateur démarre seul
2. Ctrl+Shift+P → Tasks: Run Task → Run Orchestrator (avec goal)
3. Saisir l'objectif + le chemin du repo cible

## Commandes
- make run          : lancer avec objectif
- make preflight    : vérifier l'env
- make validate     : ruff + mypy + pytest
- make logs         : voir les logs
- make stop         : arrêter
- make clean        : nettoyer
