from typing import Literal

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import ChatState


def route_after_rewrite(state: ChatState) -> Literal["retrieve", "generate_without_context"]:
    return "retrieve" if state.get("needs_retrieval", True) else "generate_without_context"


def route_after_rerank(state: ChatState) -> Literal["generate", "generate_without_context"]:
    return "generate" if state.get("documents") else "generate_without_context"


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("rerank", nodes.rerank)
    graph.add_node("generate", nodes.generate)
    graph.add_node("generate_without_context", nodes.generate_without_context)
    graph.add_node("report_usage", nodes.report_usage)

    graph.add_edge(START, "rewrite_query")
    graph.add_conditional_edges(
        "rewrite_query",
        route_after_rewrite,
        {"retrieve": "retrieve", "generate_without_context": "generate_without_context"},
    )
    graph.add_edge("retrieve", "rerank")
    graph.add_conditional_edges(
        "rerank",
        route_after_rerank,
        {"generate": "generate", "generate_without_context": "generate_without_context"},
    )
    graph.add_edge("generate", "report_usage")
    graph.add_edge("generate_without_context", "report_usage")
    graph.add_edge("report_usage", END)
    return graph.compile()
