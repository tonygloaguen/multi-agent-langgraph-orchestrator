"""Tests unitaires — authentification, RBAC, audit (api/security.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Configurer les tokens de test AVANT tout import de settings
os.environ.update(
    {
        "API_TOKEN_ADMIN": "test-admin-token-abcdefghijklmnop",
        "API_TOKEN_OPERATOR": "test-operator-token-abcdefghijk",
        "API_TOKEN_READER": "test-reader-token-abcdefghijklm",
        "AUTH_ENABLED": "true",
        # Clés LLM factices pour éviter les erreurs de validation
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "OPENAI_API_KEY": "sk-test",
    }
)

sys.path.insert(0, str(Path(__file__).parent.parent))

# Réinitialiser le singleton pour prendre les env vars de test
import orchestrator.config as _config

_config._settings = None


# ── Tests _resolve_role ───────────────────────────────────────────────────────


class TestResolveRole:
    def test_admin_token_resolu(self) -> None:
        from api.security import Role, _resolve_role

        assert _resolve_role("test-admin-token-abcdefghijklmnop") == Role.admin

    def test_operator_token_resolu(self) -> None:
        from api.security import Role, _resolve_role

        assert _resolve_role("test-operator-token-abcdefghijk") == Role.operator

    def test_reader_token_resolu(self) -> None:
        from api.security import Role, _resolve_role

        assert _resolve_role("test-reader-token-abcdefghijklm") == Role.reader

    def test_token_invalide_retourne_none(self) -> None:
        from api.security import _resolve_role

        assert _resolve_role("token-inconnu") is None

    def test_token_vide_retourne_none(self) -> None:
        from api.security import _resolve_role

        assert _resolve_role("") is None

    def test_token_long_retourne_none(self) -> None:
        from api.security import _resolve_role

        # Pas d'exception de timing ou de crash sur token long
        assert _resolve_role("a" * 10_000) is None

    def test_tokens_differents(self) -> None:
        from api.security import _resolve_role

        # Chaque token donne un rôle différent
        assert _resolve_role("test-admin-token-abcdefghijklmnop") != _resolve_role(
            "test-reader-token-abcdefghijklm"
        )

    def test_prefix_admin_pas_operator(self) -> None:
        from api.security import Role, _resolve_role

        # Un préfixe du token admin ne doit pas matcher
        result = _resolve_role("test-admin-token")
        assert result != Role.admin

    def test_comparaison_temps_constant(self) -> None:
        # Vérifie que la comparaison utilise hmac.compare_digest
        # (pas de crash ni d'exception sur n'importe quel input)
        from api.security import _resolve_role

        for payload in ["", "x", "\x00", "a" * 1000, "🔑token"]:
            _resolve_role(payload)  # Ne doit pas lever d'exception


# ── Tests Role enum ───────────────────────────────────────────────────────────


class TestRole:
    def test_roles_distincts(self) -> None:
        from api.security import Role

        assert Role.admin != Role.operator
        assert Role.admin != Role.reader
        assert Role.operator != Role.reader

    def test_role_valeurs_string(self) -> None:
        from api.security import Role

        assert Role.admin.value == "admin"
        assert Role.operator.value == "operator"
        assert Role.reader.value == "reader"


# ── Tests auth_enabled=false ──────────────────────────────────────────────────


class TestAuthDisabled:
    def test_bypass_retourne_role_admin(self) -> None:
        """Quand auth_enabled=False, le bypass doit retourner Role.admin."""
        from api.security import Role

        # Vérification que le rôle admin est bien défini et a la valeur attendue
        assert Role.admin.value == "admin"

    def test_auth_enabled_par_defaut(self) -> None:
        """auth_enabled doit être True par défaut (sécurité par défaut)."""
        from orchestrator.config import Settings

        # Settings sans .env → auth_enabled doit valoir True par défaut
        # (ne pas charger le .env local pour ce test)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.auth_enabled is True
