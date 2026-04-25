"""
nodes/schema_node.py — Answers schema-introspection questions directly.

When the user asks "list all tables", "what data do you have", etc.,
we return the table list from data_service without touching the LLM or SQL.
"""

from __future__ import annotations

from ..state import AgentState


def schema_node(state: AgentState, *, data_service) -> dict:
    """Return the list of available Databricks tables as the final answer."""
    try:
        tables = data_service.get_table_names()
    except Exception as exc:
        return {
            "final_answer": f"Could not retrieve table list: {exc}",
            "route": "schema",
        }

    if not tables:
        return {
            "final_answer": "No tables found in the connected Databricks workspace.",
            "route": "schema",
        }

    # Group by schema (e.g. chatbot_mw.default)
    grouped: dict[str, list[str]] = {}
    for full_name in sorted(tables):
        parts = full_name.rsplit(".", 1)
        schema = parts[0] if len(parts) == 2 else ""
        simple = parts[-1]
        grouped.setdefault(schema, []).append(simple)

    lines = [f"Here are the **{len(tables)} table(s)** available in the connected Databricks workspace:\n"]
    for schema, names in sorted(grouped.items()):
        if schema:
            lines.append(f"**{schema}**")
        for name in names:
            full = f"{schema}.{name}" if schema else name
            lines.append(f"- `{full}`")
        lines.append("")

    return {
        "final_answer": "\n".join(lines).strip(),
        "route": "schema",
    }
