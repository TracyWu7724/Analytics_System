"""
auth — authentication and authorisation package for the Decision System.

Public API::

    from auth import (
        AuthService,
        UserContext,
        Permission,
        RoleDefinition,
        get_current_user,
        get_optional_user,
        require_sql,
        require_rag,
        require_upload,
        require_pdf_upload,
        require_admin,
        login_for_token,
        auth_service,
    )
"""

from auth.rbac import Permission, RoleDefinition, ROLES, get_role, table_denied_for_role, rag_source_denied_for_role
from auth.user_context import UserContext
from auth.auth_service import AuthService
from auth.permission_auth import (
    auth_service,
    get_current_user,
    get_optional_user,
    require_sql,
    require_rag,
    require_upload,
    require_pdf_upload,
    require_admin,
    login_for_token,
)

__all__ = [
    # RBAC primitives
    "Permission",
    "RoleDefinition",
    "ROLES",
    "get_role",
    "table_denied_for_role",
    "rag_source_denied_for_role",
    # User identity
    "UserContext",
    # Service
    "AuthService",
    # FastAPI dependencies & helpers
    "auth_service",
    "get_current_user",
    "get_optional_user",
    "require_sql",
    "require_rag",
    "require_upload",
    "require_pdf_upload",
    "require_admin",
    "login_for_token",
]
