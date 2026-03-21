"""
api/security.py
Authentification Bearer, RBAC minimal (admin / operator / reader),
validation / sanitisation des entrées contre prompt injection.

Rôles :
  admin    — lecture + écriture + stop + admin
  operator — lecture + démarrage de runs
  reader   — lecture seule (status, history, logs)

AUTH_ENABLED=false désactive l'auth (dev local uniquement).
"""

from __future__ import annotations

import hmac
import re
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# ── Limites d'entrées ─────────────────────────────────────────────────────────

MAX_GOAL_LENGTH = 2_000
MAX_REPO_PATH_LENGTH = 500

# ── Patterns prompt injection ─────────────────────────────────────────────────
# Focalisés sur la manipulation du LLM système, pas les termes techniques.

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Redéfinition d'instructions
        r"ignore\s+(all\s+)?previous\s+instructions?",
        r"disregard\s+(all\s+)?previous\s+instructions?",
        r"forget\s+(all\s+)?previous\s+(instructions?|rules?|context)",
        # Changement de persona système
        r"you\s+are\s+now\s+(a\s+|an\s+)?(?!developer|engineer|architect)",
        r"act\s+as\s+(if\s+you\s+are|a\s+|an\s+)(?!developer|engineer|tester)",
        r"pretend\s+(you\s+are|to\s+be)\s+",
        # Exfiltration de données
        r"\bexfiltrat\w+",
        r"send\s+(all\s+)?(files?|secrets?|keys?|data)\s+to\s+",
        # Injection de balises système
        r"<\s*system\s*>",
        r"\[INST\]",
        r"<\|im_start\|>",
    ]
]

# Caractères shell dangereux dans les chemins
_DANGEROUS_PATH_CHARS = re.compile(r"[;&|`$><!\x00-\x1f]")


# ── Rôles ─────────────────────────────────────────────────────────────────────


class Role(str, Enum):
    admin = "admin"
    operator = "operator"
    reader = "reader"


# ── Résolution token → rôle ───────────────────────────────────────────────────


def _resolve_role(token: str) -> Role | None:
    """Mappe un Bearer token vers un rôle. Comparaison en temps constant (HMAC)."""
    from orchestrator.config import get_settings

    cfg = get_settings()
    candidates: list[tuple[str | None, Role]] = [
        (cfg.api_token_admin.get_secret_value() if cfg.api_token_admin else None, Role.admin),
        (cfg.api_token_operator.get_secret_value() if cfg.api_token_operator else None, Role.operator),
        (cfg.api_token_reader.get_secret_value() if cfg.api_token_reader else None, Role.reader),
    ]
    for expected, role in candidates:
        if not expected:
            continue
        if hmac.compare_digest(token.encode(), expected.encode()):
            return role
    return None


# ── Dependency FastAPI ────────────────────────────────────────────────────────


async def get_current_role(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Role:
    """Vérifie le Bearer token, retourne le rôle, injecte dans request.state."""
    from orchestrator.config import get_settings

    cfg = get_settings()

    if not cfg.auth_enabled:
        request.state.role = Role.admin
        return Role.admin

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = _resolve_role(credentials.credentials)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.role = role
    return role


def require_roles(*roles: Role):
    """Factory de dependency — exige un des rôles listés.

    Usage : Depends(require_roles(Role.admin, Role.operator))
    """

    async def _check(current: Annotated[Role, Depends(get_current_role)]) -> Role:
        if current not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current

    return _check


# ── Validation / sanitisation des entrées ────────────────────────────────────


def sanitize_goal(goal: str) -> str:
    """Valide et sanitise le champ goal.

    Rejette : vide, trop long, patterns d'injection connus.
    Retourne la valeur nettoyée (strip).
    Lève HTTPException 422 si invalide.
    """
    if not goal or not goal.strip():
        raise HTTPException(
            status_code=422,
            detail="Le champ 'goal' ne peut pas être vide",
        )
    if len(goal) > MAX_GOAL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"'goal' dépasse la limite de {MAX_GOAL_LENGTH} caractères",
        )
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(goal):
            raise HTTPException(
                status_code=422,
                detail="Contenu refusé : pattern non autorisé détecté",
            )
    return goal.strip()


def sanitize_repo_path(path: str) -> str:
    """Valide le repo_path : longueur et caractères autorisés.

    Lève HTTPException 422 si invalide.
    """
    if len(path) > MAX_REPO_PATH_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="'repo_path' dépasse la limite de longueur",
        )
    if path and _DANGEROUS_PATH_CHARS.search(path):
        raise HTTPException(
            status_code=422,
            detail="'repo_path' contient des caractères non autorisés",
        )
    return path.strip()
