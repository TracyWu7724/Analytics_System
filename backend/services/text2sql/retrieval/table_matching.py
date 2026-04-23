from typing import Any

from fuzzywuzzy import fuzz

try:
    from ..cache_service import db_cache
except ImportError:
    from cache_service import db_cache

def invalidate_table_cache() -> None:
    db_cache.invalidate_table_list()


def get_all_available_tables(service: Any) -> list[dict[str, str]]:
    cached_tables = db_cache.get_table_list(include_sql_server=True)
    if cached_tables is not None:
        return cached_tables

    table_list: list[dict[str, str]] = []

    for uploaded in service.get_uploaded_tables():
        table_list.append(
            {
                "full_name": uploaded["name"],
                "table_name": uploaded["name"],
                "schema": "uploaded",
                "description": f"Uploaded file: {uploaded.get('original_filename', '')}",
                "source": "uploaded",
            }
        )

    for table_name in service.get_table_names():
        simple_name = table_name.split(".")[-1]
        table_list.append(
            {
                "full_name": table_name,
                "table_name": simple_name,
                "schema": ".".join(table_name.split(".")[:-1]),
                "description": simple_name,
                "source": "databricks",
            }
        )

    db_cache.set_table_list(table_list, include_sql_server=True, ttl=300)
    return table_list


def get_relevant_tables(question: str, service: Any, limit: int = 5) -> list[dict[str, str | int]]:
    """Return ranked table candidates with lightweight scoring metadata."""
    question_lower = question.lower().strip()
    candidates: list[dict[str, str | int]] = []

    for table in get_all_available_tables(service):
        haystack = " ".join(
            [
                table.get("full_name", ""),
                table.get("table_name", ""),
                table.get("schema", ""),
                table.get("description", ""),
            ]
        ).lower()
        score = fuzz.token_set_ratio(question_lower, haystack)
        candidates.append({**table, "score": score})

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]


def find_best_table_match(question: str, service: Any) -> str | None:
    ranked_tables = get_relevant_tables(question, service, limit=1)
    if not ranked_tables:
        return None
    return str(ranked_tables[0]["full_name"])


def extract_table_name_from_question(question: str, service: Any) -> str:
    return find_best_table_match(question, service) or "swks_das_dev.gold"
