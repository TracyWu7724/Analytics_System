"""
UserContext — the authenticated-user object passed around the application.

Permissions are data-centric: roles control which tables and RAG source
documents a user may access, not which features they can use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auth.rbac import (
    Permission,
    RoleDefinition,
    get_role,
    rag_source_denied_for_role,
    table_denied_for_role,
)


@dataclass
class UserContext:
    """Carries identity and role information for an authenticated request.

    Attributes:
        user_id:  Opaque unique identifier (database row id as string).
        username: Human-readable login name.
        role:     Role name string (e.g. ``"analyst"``).
    """

    user_id: str
    username: str
    role: str

    @property
    def _role_def(self) -> RoleDefinition:
        return get_role(self.role)

    # ------------------------------------------------------------------
    # Feature permission checks (upload / admin gates)
    # ------------------------------------------------------------------

    def has_permission(self, permission: Permission) -> bool:
        """Return ``True`` if this role grants *permission*."""
        return permission in self._role_def.permissions

    # ------------------------------------------------------------------
    # Data-level access checks
    # ------------------------------------------------------------------

    def can_access_table(self, table_name: str) -> bool:
        """Return ``True`` if the user may query *table_name*.

        Uploaded tables (``uploaded_`` prefix) follow the same deny-list as
        Databricks tables — if the original filename matches a denied pattern
        the upload is also blocked.
        """
        return not table_denied_for_role(table_name, self._role_def)

    def can_access_rag_source(self, source: str) -> bool:
        """Return ``True`` if RAG chunks from *source* are accessible."""
        return not rag_source_denied_for_role(source, self._role_def)

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def filter_tables(self, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter *tables* (list of dicts with a ``"name"`` key) to allowed ones."""
        return [t for t in tables if self.can_access_table(t.get("name", ""))]

    def filter_rag_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove RAG chunks whose source document is denied for this role."""
        return [c for c in chunks if self.can_access_rag_source(c.get("source", ""))]

    # ------------------------------------------------------------------
    # Agent state adjustment
    # ------------------------------------------------------------------

    def adjust_agent_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of the agent *initial_state* with permission context injected.

        Adds:
        - ``denied_tables``      — list of denied table name patterns
        - ``denied_rag_sources`` — list of denied RAG source patterns
        - Clears ``uploaded_table`` if the user cannot access that table.
        """
        adjusted: dict[str, Any] = dict(state)

        role = self._role_def
        adjusted["denied_tables"] = list(role.denied_tables)
        adjusted["denied_rag_sources"] = list(role.denied_rag_sources)

        # Clear the uploaded table reference if it is denied
        uploaded_table = adjusted.get("uploaded_table")
        if uploaded_table and not self.can_access_table(uploaded_table):
            adjusted["uploaded_table"] = None

        return adjusted
