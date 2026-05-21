import pytest
from backend.app.agent.graph import build_agent_graph
from backend.app.agent.state import AgentState


def test_graph_compiles():
    graph = build_agent_graph()
    assert graph is not None


def test_agent_state_structure():
    state: AgentState = {
        "messages": [],
        "session_id": "test-123",
        "query": "What is Amazon S3?",
        "rewritten_query": "",
        "retrieved_docs": [],
        "relevant_docs": [],
        "final_answer": "",
        "citations": [],
        "iterations": 0,
        "should_retrieve_live": False,
    }
    assert state["query"] == "What is Amazon S3?"
    assert state["iterations"] == 0