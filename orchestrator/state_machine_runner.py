"""
orchestrator/state_machine_runner.py
Wrapper CLI appelé par le serveur FastAPI en subprocess.
Redirige les prints rich vers stdout pour le streaming SSE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Forcer stdout unbuffered pour le streaming
sys.stdout.reconfigure(line_buffering=True)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--goal", default="")
    p.add_argument("--repo", default="")
    p.add_argument("--run-id", default="")
    args = p.parse_args()

    # Ajouter le projet au path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    from orchestrator.state_machine import run_pipeline

    run_pipeline(goal=args.goal, repo_path=args.repo)
