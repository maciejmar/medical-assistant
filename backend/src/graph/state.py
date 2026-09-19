from typing import Annotated, Any, TypedDict


def merge_usage(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    """Reducer sumujący zużycie tokenów ze wszystkich węzłów grafu w jednym żądaniu."""
    merged = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for part in (left, right):
        if part:
            for key in merged:
                merged[key] += int(part.get(key, 0))
    return merged


class ChatState(TypedDict, total=False):
    user_id: int
    question: str
    history: list[dict[str, str]]
    patient_context: str | None

    rewritten_query: str
    needs_retrieval: bool
    filters: dict[str, str]

    candidates: list[dict[str, Any]]
    documents: list[dict[str, Any]]

    answer: str
    usage: Annotated[dict[str, int], merge_usage]
