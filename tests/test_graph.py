"""Tests unitaires — graphe LangGraph (structure et routeurs)."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBuildGraph:
    def test_graphe_compile(self):
        from orchestrator.state_machine import build_graph
        graph = build_graph()
        assert graph is not None

    def test_noeuds_presents(self):
        from orchestrator.state_machine import build_graph
        graph = build_graph()
        nodes = list(graph.get_graph().nodes.keys())
        required = [
            "init", "preflight", "snapshot", "plan",
            "prepare_task", "implement", "validate",
            "analyze", "repair", "review", "commit",
            "skip_task", "done"
        ]
        for node in required:
            assert node in nodes, f"Nœud manquant : {node}"

    def test_nombre_noeuds(self):
        from orchestrator.state_machine import build_graph
        graph = build_graph()
        nodes = list(graph.get_graph().nodes.keys())
        # __start__ et __end__ sont ajoutés automatiquement par LangGraph
        assert len(nodes) >= 13


class TestRouteurs:
    def test_route_preflight_ok(self):
        from orchestrator.state_machine import route_after_preflight
        state = {"status": "running", "errors": []}
        assert route_after_preflight(state) == "snapshot"

    def test_route_preflight_fail(self):
        from orchestrator.state_machine import route_after_preflight
        state = {"status": "failed", "errors": ["Erreur"]}
        assert route_after_preflight(state) == "done"

    def test_route_plan_ok(self):
        from orchestrator.state_machine import route_after_plan
        state = {
            "status": "running",
            "tasks": [{"task_id": "task-001"}],
        }
        assert route_after_plan(state) == "prepare_task"

    def test_route_plan_fail(self):
        from orchestrator.state_machine import route_after_plan
        state = {"status": "failed", "tasks": []}
        assert route_after_plan(state) == "done"

    def test_route_plan_vide(self):
        from orchestrator.state_machine import route_after_plan
        state = {"status": "running", "tasks": []}
        assert route_after_plan(state) == "done"

    def test_route_validate_pass(self):
        from orchestrator.state_machine import route_after_validate
        state = {
            "validation_passed": True,
            "repair_attempts": 0,
        }
        assert route_after_validate(state) == "review"

    def test_route_validate_fail_premier_essai(self):
        from orchestrator.state_machine import route_after_validate
        state = {
            "validation_passed": False,
            "repair_attempts": 0,
        }
        assert route_after_validate(state) == "analyze"

    def test_route_validate_max_repairs(self):
        from orchestrator.state_machine import route_after_validate
        from orchestrator.config import get_settings
        cfg = get_settings()
        state = {
            "validation_passed": False,
            "repair_attempts": cfg.orchestrator_max_repair_loops,
        }
        # Max atteint → review quand même pour tracer
        assert route_after_validate(state) == "review"

    def test_route_analyze_escalade(self):
        from orchestrator.state_machine import route_after_analyze
        state = {"escalated": True}
        assert route_after_analyze(state) == "review"

    def test_route_analyze_repair(self):
        from orchestrator.state_machine import route_after_analyze
        state = {"escalated": False}
        assert route_after_analyze(state) == "repair"

    def test_route_commit_suite(self):
        from orchestrator.state_machine import route_after_commit
        state = {
            "tasks":      [{"id": "t1"}, {"id": "t2"}],
            "task_index": 1,  # index APRÈS incrément = 1 < 2
        }
        assert route_after_commit(state) == "prepare_task"

    def test_route_commit_fin(self):
        from orchestrator.state_machine import route_after_commit
        state = {
            "tasks":      [{"id": "t1"}, {"id": "t2"}],
            "task_index": 2,  # index APRÈS incrément = 2 == len
        }
        assert route_after_commit(state) == "done"
