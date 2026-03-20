#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-.}"
echo "=== Validation : $(date) | Repo : $REPO ==="
ok=true

echo ">>> ruff"
ruff check "$REPO" --output-format=concise && echo "[OK] ruff" || { echo "[FAIL] ruff"; ok=false; }

echo ">>> mypy"
mypy "$REPO" --ignore-missing-imports && echo "[OK] mypy" || { echo "[FAIL] mypy"; ok=false; }

echo ">>> pytest"
pytest "$REPO" -q --tb=short 2>&1 | tail -10 && echo "[OK] pytest" || { echo "[FAIL] pytest"; ok=false; }

$ok && echo "=== PASS ===" || { echo "=== FAIL ==="; exit 1; }
