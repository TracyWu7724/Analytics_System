"""
Role-based access control definitions for the Decision System.

Permissions are data-centric, not feature-centric:
- All authenticated roles can use SQL and RAG.
- Roles differ in *which tables* and *which RAG source documents* they can see.

``denied_tables``      — substring patterns matched against table names (case-insensitive).
                         Any table whose name contains a pattern is blocked.
``denied_rag_sources`` — substring patterns matched against RAG chunk source filenames.
                         Any chunk whose source contains a pattern is filtered out before
                         the LLM sees it.

Feature-level gates (upload, admin) are kept as a thin Permission enum so the
API layer can still guard upload endpoints independently of data restrictions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Permission(str, Enum):
    """Coarse feature permissions — separate from data-level access control."""
    file_upload = "file_upload"   # upload CSV / Excel data tables
    pdf_upload  = "pdf_upload"    # add PDFs to the RAG knowledge base
    admin       = "admin"         # user management and system config


@dataclass(frozen=True)
class RoleDefinition:
    """Describes what a role may and may not see.

    Attributes:
        name:               Canonical role name string (e.g. ``"analyst"``).
        permissions:        Set of coarse :class:`Permission` values.
        denied_tables:      Substring patterns of table names that are blocked.
                            An empty list means *all tables* are accessible.
        denied_rag_sources: Substring patterns of RAG source filenames that are
                            blocked.  An empty list means *all documents* are
                            accessible.
    """
    name: str
    permissions: set[Permission]
    denied_tables: list[str] = field(default_factory=list)
    denied_rag_sources: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Role registry
# ---------------------------------------------------------------------------

ROLES: dict[str, RoleDefinition] = {
    "admin": RoleDefinition(
        name="admin",
        permissions={Permission.file_upload, Permission.pdf_upload, Permission.admin},
        denied_tables=[],        # no restrictions
        denied_rag_sources=[],   # no restrictions
    ),
    "analyst": RoleDefinition(
        name="analyst",
        permissions={Permission.file_upload, Permission.pdf_upload},
        # Cannot query sales or budget tables
        denied_tables=["sales_data", "project_budget"],
        # Cannot see LOCTITE AA product family documents
        denied_rag_sources=["LOCTITE-AA"],
    ),
    "manager": RoleDefinition(
        name="manager",
        permissions=set(),
        denied_tables=[],
        denied_rag_sources=[],
    ),
    "viewer": RoleDefinition(
        name="viewer",
        permissions=set(),
        denied_tables=["sales_data", "project_budget"],
        denied_rag_sources=["LOCTITE-AA"],
    ),
}


def get_role(role_name: str) -> RoleDefinition:
    """Return the :class:`RoleDefinition` for *role_name*.

    Raises:
        KeyError: If the role is not defined.
    """
    return ROLES[role_name]


def table_denied_for_role(table_name: str, role_def: RoleDefinition) -> bool:
    """Return ``True`` if *table_name* is blocked for *role_def*.

    Matching is case-insensitive substring search.
    """
    lower = table_name.lower()
    return any(pattern.lower() in lower for pattern in role_def.denied_tables)


def rag_source_denied_for_role(source: str, role_def: RoleDefinition) -> bool:
    """Return ``True`` if the RAG chunk *source* filename is blocked for *role_def*."""
    return any(pattern in source for pattern in role_def.denied_rag_sources)
