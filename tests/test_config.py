"""Tests unitaires — config.py."""
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSettings:
    def test_chargement_settings(self):
        from orchestrator.config import get_settings
        cfg = get_settings()
        assert cfg is not None

    def test_dirs_existent(self):
        from orchestrator.config import get_settings
        cfg = get_settings()
        assert cfg.handoffs_dir is not None
        assert cfg.state_dir is not None
        assert cfg.logs_dir is not None

    def test_max_repair_loops_valide(self):
        from orchestrator.config import get_settings
        cfg = get_settings()
        assert 1 <= cfg.orchestrator_max_repair_loops <= 5

    def test_rtk_available_est_bool(self):
        from orchestrator.config import get_settings
        cfg = get_settings()
        assert isinstance(cfg.rtk_available, bool)

    def test_ensure_dirs_cree_dossiers(self):
        from orchestrator.config import get_settings
        cfg = get_settings()
        cfg.ensure_dirs()
        # Les dossiers doivent exister après ensure_dirs
        assert Path(cfg.handoffs_dir).exists()
        assert Path(cfg.state_dir).exists()
        assert Path(cfg.logs_dir).exists()
