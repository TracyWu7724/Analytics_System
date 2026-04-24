"""
FastAPI dependency functions for authentication and authorization.

Provides ``get_current_user`` (and related ``require_*`` variants) for use as
FastAPI ``Depends`` arguments, plus a module-level :class:`~auth.auth_service.AuthService`
singleton and a ``login_for_token`` helper.

Usage example::

    from auth.permission_auth import get_current_user, require_sql

    @app.post("/query")
    async def query(user: UserContext = Depends(require_sql)):
        ...
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from auth.auth_service import AuthService
from auth.rbac import Permission
from auth.user_context import UserContext

# ---------------------------------------------------------------------------
# Module-level singleton — initialises the DB (and seeds demo users) on import
# ---------------------------------------------------------------------------

auth_service = AuthService()
auth_service.init_db()


# ---------------------------------------------------------------------------
# Token extraction helper
# ---------------------------------------------------------------------------


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Return the raw token from an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------


def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> UserContext:
    """FastAPI dependency — extract and verify the Bearer token.

    Raises:
        HTTPException 401: If the header is absent, malformed, or the token is
            invalid/expired.
    """
    token = _extract_bearer(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = auth_service.verify_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_user(
    authorization: Optional[str] = Header(default=None),
) -> Optional[UserContext]:
    """FastAPI dependency — like :func:`get_current_user` but returns ``None``
    instead of raising an exception when no valid token is present.

    Intended for backward-compatible rollout where unauthenticated requests
    should still be served (with reduced permissions).
    """
    token = _extract_bearer(authorization)
    if token is None:
        return None
    return auth_service.verify_token(token)  # None on invalid/expired


# ---------------------------------------------------------------------------
# Permission-scoped dependencies
# ---------------------------------------------------------------------------


def require_sql(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require authentication to use SQL.

    All authenticated roles can run SQL queries; data-level restrictions are
    enforced via ``denied_tables`` in the agent state, not feature permissions.
    """
    return user


def require_rag(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require authentication to use RAG.

    All authenticated roles can run RAG queries; data-level restrictions are
    enforced via ``denied_rag_sources`` in the agent state, not feature permissions.
    """
    return user


def require_upload(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require the ``file_upload`` permission.

    Raises:
        HTTPException 403: If the user lacks the permission.
    """
    if not user.has_permission(Permission.file_upload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="file_upload permission required.",
        )
    return user


def require_pdf_upload(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require the ``pdf_upload`` permission.

    Raises:
        HTTPException 403: If the user lacks the permission.
    """
    if not user.has_permission(Permission.pdf_upload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="pdf_upload permission required.",
        )
    return user


def require_admin(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require the ``admin`` permission.

    Raises:
        HTTPException 403: If the user is not an admin.
    """
    if not user.has_permission(Permission.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required.",
        )
    return user


# ---------------------------------------------------------------------------
# Login helper
# ---------------------------------------------------------------------------


def login_for_token(username: str, password: str) -> str:
    """Authenticate *username* / *password* and return a signed token string.

    Uses the module-level :data:`auth_service` singleton.

    Raises:
        HTTPException 401: On invalid credentials.
    """
    user = auth_service.verify_password(username, password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_service.create_token(user)
