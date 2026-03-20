.PHONY: bootstrap install preflight run validate clean logs stop help

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip

bootstrap:
	bash scripts/bootstrap.sh

install:
	$(PIP) install -q -r requirements.txt

preflight:
	$(PYTHON) scripts/preflight.py

validate:
	bash scripts/validate_task.sh .

run:
	@read -p "Objectif : " goal; \
	read -p "Repo cible (Entrée = projet courant) : " repo; \
	repo=$${repo:-.}; \
	$(PYTHON) orchestrator/state_machine.py --goal "$$goal" --repo "$$repo"

start:
	bash scripts/start_orchestrator.sh

stop:
	pkill -f state_machine.py || echo "Non actif"

logs:
	tail -f logs/orchestrator.log

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	echo "Nettoyé"

clean-handoffs:
	rm -f orchestrator/handoffs/*.yaml && echo "Handoffs supprimés"

help:
	@echo ""
	@echo "  bootstrap      Installation complète (première fois)"
	@echo "  run            Lancer avec objectif + repo cible"
	@echo "  preflight      Vérifier l'environnement"
	@echo "  validate       ruff + mypy + pytest"
	@echo "  logs           Tail des logs en temps réel"
	@echo "  stop           Arrêter l'orchestrateur"
	@echo "  clean          Nettoyer les artefacts"
	@echo ""

.DEFAULT_GOAL := help
