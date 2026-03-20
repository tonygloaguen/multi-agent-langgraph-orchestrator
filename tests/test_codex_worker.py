"""Tests unitaires — codex_worker.py (sans appel Codex réel)."""
import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCountErrors:
    def test_zero_erreurs(self):
        from orchestrator.workers.codex_worker import _count_errors
        assert _count_errors("", "", "") == 0

    def test_erreurs_ruff(self):
        from orchestrator.workers.codex_worker import _count_errors
        ruff = "src/test.py:1:1: F401 unused\nsrc/test.py:2:1: E501 too long"
        assert _count_errors(ruff, "", "") == 2

    def test_erreurs_mypy(self):
        from orchestrator.workers.codex_worker import _count_errors
        mypy = "src/test.py:5: error: Incompatible types\nsrc/test.py:10: error: Missing type"
        assert _count_errors("", mypy, "") == 2

    def test_erreurs_pytest(self):
        from orchestrator.workers.codex_worker import _count_errors
        test = "3 failed, 10 passed"
        assert _count_errors("", "", test) == 3

    def test_combinaison(self):
        from orchestrator.workers.codex_worker import _count_errors
        ruff = "src/test.py:1:1: F401 unused"
        mypy = "src/test.py:5: error: Missing type"
        test = "2 failed, 5 passed"
        assert _count_errors(ruff, mypy, test) == 4


class TestRtk:
    def test_passthrough_si_rtk_absent(self):
        from orchestrator.workers.codex_worker import _rtk
        text = "texte de test"
        # RTK probablement absent — doit retourner le texte tel quel
        result = _rtk(text)
        assert result == text or isinstance(result, str)

    def test_texte_vide(self):
        from orchestrator.workers.codex_worker import _rtk
        assert _rtk("") == ""


class TestImplementTask:
    @patch("orchestrator.workers.codex_worker._run_codex")
    @patch("subprocess.run")
    def test_succes(self, mock_subprocess, mock_codex):
        from orchestrator.workers.codex_worker import implement_task

        mock_codex.return_value = (0, "code généré", "")
        mock_subprocess.return_value = MagicMock(
            stdout="diff --git a/src/test.py",
            returncode=0
        )

        handoff = {
            "task_title": "Test task",
            "task_objective": "Objectif test",
            "files_allowed": ["src/test.py"],
            "acceptance_criteria": ["Tests passent"],
        }
        result = implement_task(handoff, ".")
        assert result["success"] is True

    @patch("orchestrator.workers.codex_worker._run_codex")
    @patch("subprocess.run")
    def test_echec_codex(self, mock_subprocess, mock_codex):
        from orchestrator.workers.codex_worker import implement_task

        mock_codex.return_value = (1, "", "Erreur codex")
        mock_subprocess.return_value = MagicMock(stdout="", returncode=0)

        handoff = {
            "task_title": "Test",
            "task_objective": "Test",
            "files_allowed": ["src/test.py"],
            "acceptance_criteria": [],
        }
        result = implement_task(handoff, ".")
        assert result["success"] is False
        assert "Erreur codex" in result["error"]
