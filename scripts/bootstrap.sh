#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "======================================"
echo " Bootstrap — Multi-Agent Orchestrator"
echo " $(date)"
echo "======================================"

command -v python3 >/dev/null || fail "python3 manquant"
PY=$(python3 -c "import sys; print(int(sys.version_info >= (3,11)))")
[[ "$PY" == "1" ]] || fail "Python >= 3.11 requis"
ok "Python $(python3 --version)"

command -v node >/dev/null || fail "Node.js manquant"
command -v npm  >/dev/null || fail "npm manquant"
ok "Node $(node --version) / npm $(npm --version)"

if [[ ! -f ".env" ]]; then
    cp .env.example .env
    warn ".env créé — RENSEIGNER les clés API avant de continuer"
    echo ""
    echo "  Ouvrir .env et renseigner :"
    echo "    ANTHROPIC_API_KEY=sk-ant-..."
    echo "    OPENAI_API_KEY=sk-..."
    echo ""
    read -p "Appuyer sur Entrée après avoir sauvegardé .env..." _
fi
set -a; source .env; set +a
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && [[ "${ANTHROPIC_API_KEY}" != *"VOTRE_CLE"* ]] \
    || fail "ANTHROPIC_API_KEY non renseignée dans .env"
[[ -n "${OPENAI_API_KEY:-}" ]] && [[ "${OPENAI_API_KEY}" != *"VOTRE_CLE"* ]] \
    || fail "OPENAI_API_KEY non renseignée dans .env"
ok "Clés API présentes"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    ok "venv créé"
else
    ok "venv existant"
fi
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dépendances Python installées"

python3 -c "import langgraph, langchain_anthropic, pydantic, yaml, rich" \
    || fail "Import check échoué"
ok "Imports Python OK"

command -v codex >/dev/null \
    && ok "Codex CLI : $(codex --version 2>/dev/null || echo 'ok')" \
    || fail "Codex CLI non trouvé — lancer : npm install -g @openai/codex"

chmod +x scripts/*.sh
ok "Scripts exécutables"

echo ""
echo "======================================"
echo -e "${GREEN} Bootstrap terminé avec succès.${NC}"
echo ""
echo " Étape suivante :"
echo "   code $(pwd)"
echo "   → Cliquer 'Allow' sur la notification VS Code"
echo "   → L'orchestrateur démarre automatiquement"
echo "======================================"
