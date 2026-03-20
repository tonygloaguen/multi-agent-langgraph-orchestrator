"""Tests unitaires — journalisation HMAC NIS2."""

import json
import hmac
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSignEntry:
    def test_signature_reproductible(self):
        from orchestrator.state_machine import _sign_entry

        entry = {"event": "test", "run_id": "run-001", "ts": "2026-01-01"}
        sig1 = _sign_entry(entry)
        sig2 = _sign_entry(entry)
        assert sig1 == sig2

    def test_signature_differente_si_contenu_different(self):
        from orchestrator.state_machine import _sign_entry

        entry1 = {"event": "test1", "run_id": "run-001"}
        entry2 = {"event": "test2", "run_id": "run-001"}
        assert _sign_entry(entry1) != _sign_entry(entry2)

    def test_signature_est_hex(self):
        from orchestrator.state_machine import _sign_entry

        entry = {"event": "test", "run_id": "run-001"}
        sig = _sign_entry(entry)
        assert len(sig) == 64  # SHA256 = 64 hex chars
        int(sig, 16)  # Doit être un hex valide


class TestLogEvent:
    def test_entree_ecrite(self):
        from orchestrator.state_machine import _log_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            _log_event("run-test", "test_event", {"key": "value"}, log_dir)
            log_file = log_dir / "run-test.jsonl"
            assert log_file.exists()
            entry = json.loads(log_file.read_text().strip())
            assert entry["event"] == "test_event"
            assert entry["key"] == "value"
            assert "signature" in entry

    def test_signature_valide(self):
        from orchestrator.state_machine import _log_event, _sign_entry

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            _log_event("run-test", "test_event", {"data": "important"}, log_dir)
            log_file = log_dir / "run-test.jsonl"
            entry = json.loads(log_file.read_text().strip())
            sig = entry.pop("signature")
            expected = _sign_entry(entry)
            assert hmac.compare_digest(sig, expected)

    def test_multiple_entrees(self):
        from orchestrator.state_machine import _log_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            for i in range(3):
                _log_event("run-test", f"event_{i}", {"i": i}, log_dir)
            log_file = log_dir / "run-test.jsonl"
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 3


class TestVerifyJournal:
    def test_journal_integre(self):
        from orchestrator.state_machine import _log_event

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            _log_event("run-verify", "pipeline_start", {"goal": "test"}, log_dir)
            _log_event("run-verify", "pipeline_completed", {"total": 3}, log_dir)
            log_file = log_dir / "run-verify.jsonl"
            # Vérifier manuellement les signatures
            for line in log_file.read_text().strip().split("\n"):
                entry = json.loads(line)
                assert "signature" in entry
                assert len(entry["signature"]) == 64
