#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "======================================"
echo " Multi-Agent Orchestrator"
echo " $(date)"
echo "======================================"

if [[ ! -f ".env" ]]; then
    echo "[WARN] .env absent — lancer d'abord : bash scripts/bootstrap.sh"
    exit 1
fi
set -a; source .env; set +a
echo "[OK] .env chargé"

if [[ ! -d ".venv" ]]; then
    echo "[WARN] venv absent — lancement bootstrap..."
    bash scripts/bootstrap.sh
fi
source .venv/bin/activate
echo "[OK] venv activé : $(python --version)"

echo ""
echo "--- Preflight rapide ---"
python scripts/preflight.py --mode=quick
RC=$?
if [[ $RC -eq 1 ]]; then
    echo ""
    echo "[FAIL] Erreurs bloquantes détectées."
    echo "Lancer : bash scripts/bootstrap.sh"
    exit 1
fi

echo ""
echo "================================================"
echo " Orchestrateur prêt."
echo ""
echo " Pour lancer une tâche :"
echo "   Dans VS Code : Ctrl+Shift+P"
echo "   → Tasks: Run Task"
echo "   → Run Orchestrator (avec goal)"
echo ""
echo "   Ou en terminal : make run"
echo "================================================"
echo ""

# Garder le terminal ouvert (log en attente)
tail -f /dev/null
