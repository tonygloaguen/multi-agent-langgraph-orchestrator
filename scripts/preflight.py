#!/usr/bin/env python3
"""Vérification de l'environnement. Exit 0=OK, 1=erreur, 2=warning."""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def chk(label: str, ok: bool, detail: str = "", blocking: bool = True) -> bool:
    icon = "OK  " if ok else ("FAIL" if blocking else "WARN")
    color = "\033[32m" if ok else ("\033[31m" if blocking else "\033[33m")
    print(f"  {color}[{icon}]\033[0m {label}" + (f" — {detail}" if detail else ""))
    return ok


def run(cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return r.returncode, (r.stdout + r.stderr).strip()


def main() -> int:
    print("\n=== Preflight Check ===\n")
    failures, warnings = [], []

    # Python
    v = sys.version_info
    ok = v >= (3, 11)
    if not chk("Python >= 3.11", ok, f"{v.major}.{v.minor}"):
        failures.append("python")

    # .env et clés API
    env_file = Path(".env")
    if not chk(".env présent", env_file.exists(), blocking=False):
        warnings.append(".env")
    else:
        content = env_file.read_text()
        for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
            val = ""
            for line in content.splitlines():
                if line.startswith(f"{var}="):
                    val = line.split("=", 1)[1].strip()
            has_val = bool(val) and "VOTRE_CLE" not in val
            if not chk(
                var, has_val, "présente" if has_val else "manquante ou non renseignée"
            ):
                failures.append(var)

    # Outils obligatoires
    for tool in ["git", "codex"]:
        rc, out = run(f"which {tool}")
        if not chk(tool, rc == 0, out.split("\n")[0][:50]):
            failures.append(tool)

    # Outils dans venv (optionnels si venv pas encore actif)
    for tool in ["ruff", "mypy", "pytest"]:
        rc, out = run(f"which {tool}")
        if not chk(tool, rc == 0, out.split("\n")[0][:50], blocking=False):
            warnings.append(tool)

    # Venv
    venv = Path(".venv")
    if not chk("venv .venv/", venv.exists(), blocking=False):
        warnings.append("venv")

    # Imports Python (seulement si venv actif)
    if venv.exists():
        for mod in ["langgraph", "langchain_anthropic", "pydantic", "yaml", "rich"]:
            try:
                __import__(mod)
                chk(f"import {mod}", True)
            except ImportError:
                if not chk(
                    f"import {mod}",
                    False,
                    "pip install -r requirements.txt",
                    blocking=False,
                ):
                    warnings.append(f"import:{mod}")

    print()
    if failures:
        print(f"\033[31mFAIL\033[0m — {len(failures)} erreur(s) : {failures}")
        return 1
    if warnings:
        print(f"\033[33mWARN\033[0m — {len(warnings)} avertissement(s) : {warnings}")
        return 2
    print("\033[32mOK\033[0m — Environnement prêt.")
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="full")
    p.parse_args()
    sys.exit(main())
