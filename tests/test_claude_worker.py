"""Tests unitaires — claude_worker.py (sans appel API réel)."""
import json
import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCleanMarkdown:
    def test_sans_balises(self):
        from orchestrator.workers.claude_worker import _clean_markdown
        assert _clean_markdown("texte simple") == "texte simple"

    def test_balise_yaml(self):
        from orchestrator.workers.claude_worker import _clean_markdown
        raw = "```yaml\nplan_id: test\n```"
        assert _clean_markdown(raw) == "plan_id: test"

    def test_balise_json(self):
        from orchestrator.workers.claude_worker import _clean_markdown
        raw = '```json\n{"key": "value"}\n```'
        assert _clean_markdown(raw) == '{"key": "value"}'

    def test_balise_vide(self):
        from orchestrator.workers.claude_worker import _clean_markdown
        raw = "```\ncontenu\n```"
        assert _clean_markdown(raw) == "contenu"

    def test_sans_fermeture(self):
        from orchestrator.workers.claude_worker import _clean_markdown
        raw = "```yaml\nplan_id: test"
        result = _clean_markdown(raw)
        assert "plan_id: test" in result


class TestExtractJson:
    def test_json_valide(self):
        from orchestrator.workers.claude_worker import _extract_json
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_avec_texte_avant(self):
        from orchestrator.workers.claude_worker import _extract_json
        result = _extract_json('Voici la réponse: {"key": "value"}')
        assert result["key"] == "value"

    def test_json_invalide(self):
        from orchestrator.workers.claude_worker import _extract_json
        with pytest.raises(ValueError):
            _extract_json("pas de json ici")

    def test_json_imbriqué(self):
        from orchestrator.workers.claude_worker import _extract_json
        raw = '{"root_cause": "test", "escalate": false}'
        result = _extract_json(raw)
        assert result["escalate"] is False


class TestGeneratePlan:
    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_plan_valide(self, mock_claude):
        from orchestrator.workers.claude_worker import generate_plan
        mock_claude.return_value = """plan_id: plan-20260320-001
description: "test"
tasks:
  - task_id: "task-001"
    kind: implementation
    title: "Test"
    objective: "Objectif test"
    files_allowed:
      - "src/test.py"
    acceptance_criteria:
      - "Tests passent"
"""
        result = generate_plan("test goal", "snapshot")
        assert result["plan_id"] == "plan-20260320-001"
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["task_id"] == "task-001"

    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_plan_yaml_invalide(self, mock_claude):
        from orchestrator.workers.claude_worker import generate_plan
        mock_claude.return_value = "pas du yaml valide {"
        with pytest.raises(RuntimeError):
            generate_plan("test", "snapshot")

    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_plan_sans_tasks(self, mock_claude):
        from orchestrator.workers.claude_worker import generate_plan
        mock_claude.return_value = "plan_id: test\ndescription: test"
        with pytest.raises(RuntimeError):
            generate_plan("test", "snapshot")


class TestAnalyzeFailure:
    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_analyse_reussie(self, mock_claude):
        from orchestrator.workers.claude_worker import analyze_failure
        mock_claude.return_value = json.dumps({
            "root_cause": "Import inutilisé",
            "repair_hints": ["Supprimer l'import ligne 5"],
            "files_to_fix": ["src/test.py"],
            "escalate": False,
        })
        result = analyze_failure("F401 unused", "", "", "", ["src/test.py"])
        assert result["escalate"] is False
        assert len(result["repair_hints"]) > 0

    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_fallback_si_json_invalide(self, mock_claude):
        from orchestrator.workers.claude_worker import analyze_failure
        mock_claude.return_value = "réponse non JSON"
        result = analyze_failure("erreur", "", "", "", ["src/test.py"])
        assert "root_cause" in result
        assert result["escalate"] is False

    @patch("orchestrator.workers.claude_worker._call_claude")
    def test_escalade_detectee(self, mock_claude):
        from orchestrator.workers.claude_worker import analyze_failure
        mock_claude.return_value = json.dumps({
            "root_cause": "Refactor architectural nécessaire",
            "repair_hints": [],
            "files_to_fix": [],
            "escalate": True,
        })
        result = analyze_failure("erreur", "", "", "", ["src/test.py"])
        assert result["escalate"] is True
