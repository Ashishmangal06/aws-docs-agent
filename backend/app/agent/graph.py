import logging
from langgraph.graph import StateGraph, END

from backend.app.agent.state import AgentState
from backend.app.agent.nodes import (
    query_rewriter_node,
    retriever_node,
    grader_node,
    live_fetcher_node,
    responder_node,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3


def should_use_live_fetch(state: AgentState) -> str:
    """
    Conditional edge after grader:
    - If no relevant docs found → go to live_fetcher
    - Otherwise → go straight to responder
    """
    if state.get("should_retrieve_live", False):
        logger.info("Routing → live_fetcher")
        return "live_fetcher"
    return "responder"


def should_continue_or_end(state: AgentState) -> str:
    """
    Safety valve: if iterations exceed MAX, force end.
    """
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        logger.warning("Max iterations reached — forcing END")
        return END
    return "query_rewriter"


def build_agent_graph() -> StateGraph:
    """
    Builds and compiles the full LangGraph agent.

    Flow:
    START
      └── query_rewriter
            └── retriever
                  └── grader
                        ├── (relevant) ──→ responder ──→ END
                        └── (not relevant) → live_fetcher → responder → END
    """
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("query_rewriter", query_rewriter_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("grader", grader_node)
    graph.add_node("live_fetcher", live_fetcher_node)
    graph.add_node("responder", responder_node)

    # Entry point
    graph.set_entry_point("query_rewriter")

    # Fixed edges
    graph.add_edge("query_rewriter", "retriever")
    graph.add_edge("retriever", "grader")
    graph.add_edge("live_fetcher", "responder")
    graph.add_edge("responder", END)

    # Conditional edge after grader
    graph.add_conditional_edges(
        "grader",
        should_use_live_fetch,
        {
            "live_fetcher": "live_fetcher",
            "responder": "responder",
        },
    )

    compiled = graph.compile()
    logger.info("LangGraph agent compiled successfully")
    return compiled


# Module-level singleton — compiled once, reused per request
agent_graph = build_agent_graph()