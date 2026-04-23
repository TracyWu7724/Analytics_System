"""Helpers for surfacing similar recent natural-language questions."""

from __future__ import annotations

from fuzzywuzzy import fuzz


def get_relevant_query_history(question: str, data_service, limit: int = 3) -> list[dict]:
    """Return recent saved questions ranked by similarity to the current request."""
    question_lower = question.lower().strip()
    recent_queries = data_service.get_recent_queries(20)

    scored_queries = []
    for item in recent_queries:
        query_text = item.get("query_text", "")
        if not query_text:
            continue
        score = fuzz.token_set_ratio(question_lower, query_text.lower())
        scored_queries.append(
            {
                "query_text": query_text,
                "created_at": item.get("created_at"),
                "score": score,
            }
        )

    scored_queries.sort(key=lambda item: item["score"], reverse=True)
    return scored_queries[:limit]
