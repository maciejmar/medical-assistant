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
    # Tryb szablonu (pastylka): {"name", "body", "long_answer"}, opisy ćwiczeń z katalogu
    # (dokumenty źródłowe) i nazwy ćwiczeń bez opisu w katalogu.
    template: dict[str, Any] | None
    template_documents: list[dict[str, Any]]
    template_missing: list[str]

    rewritten_query: str
    filters: dict[str, str]

    candidates: list[dict[str, Any]]
    documents: list[dict[str, Any]]

    answer: str
    usage: Annotated[dict[str, int], merge_usage]
