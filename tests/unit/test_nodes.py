"""Unit tests for LangGraph nodes — no AWS calls made."""

from unittest.mock import MagicMock, patch
from langchain.schema import Document, AIMessage
from backend.app.agent.state import AgentState
from backend.app.agent.nodes import (
    query_rewriter_node,
    grader_node,
    responder_node,
)


def _base_state(**overrides) -> AgentState:
    base = {
        "messages": [],
        "session_id": "test-session",
        "query": "What is Amazon S3?",
        "rewritten_query": "",
        "retrieved_docs": [],
        "relevant_docs": [],
        "final_answer": "",
        "citations": [],
        "iterations": 0,
        "should_retrieve_live": False,
    }
    base.update(overrides)
    return base


def _mock_doc(content: str, url: str = "https://docs.aws.amazon.com/s3") -> Document:
    return Document(
        page_content=content,
        metadata={"source_url": url, "service_name": "s3", "page_title": "S3 Docs"},
    )


class TestQueryRewriterNode:

    @patch("backend.app.agent.nodes._get_llm")
    def test_rewrites_vague_query(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="Amazon S3 object storage overview"
        )
        mock_get_llm.return_value = mock_llm
        state = _base_state(query="how do I store files?")
        result = query_rewriter_node(state)
        assert result["rewritten_query"] == "Amazon S3 object storage overview"
        assert result["iterations"] == 1

    def test_skips_rewrite_for_short_query(self):
        state = _base_state(query="S3 limits")
        result = query_rewriter_node(state)
        assert result["rewritten_query"] == "S3 limits"

    @patch("backend.app.agent.nodes._get_llm")
    def test_increments_iterations(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="rewritten")
        mock_get_llm.return_value = mock_llm
        state = _base_state(query="tell me about networking", iterations=2)
        result = query_rewriter_node(state)
        assert result["iterations"] == 3


class TestGraderNode:

    @patch("backend.app.agent.nodes._get_llm")
    def test_marks_relevant_doc(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content='{"relevant": true}')
        mock_get_llm.return_value = mock_llm
        state = _base_state(
            query="What is the max S3 object size?",
            retrieved_docs=[_mock_doc("S3 supports up to 5TB objects")],
        )
        result = grader_node(state)
        assert len(result["relevant_docs"]) == 1
        assert result["should_retrieve_live"] is False

    @patch("backend.app.agent.nodes._get_llm")
    def test_irrelevant_doc_triggers_live_fetch(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content='{"relevant": false}')
        mock_get_llm.return_value = mock_llm
        state = _base_state(
            query="What is the max S3 object size?",
            retrieved_docs=[_mock_doc("EC2 instance types overview")],
        )
        result = grader_node(state)
        assert len(result["relevant_docs"]) == 0
        assert result["should_retrieve_live"] is True

    @patch("backend.app.agent.nodes._get_llm")
    def test_fails_open_on_json_error(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="not valid json")
        mock_get_llm.return_value = mock_llm
        state = _base_state(retrieved_docs=[_mock_doc("some content")])
        result = grader_node(state)
        assert len(result["relevant_docs"]) == 1


class TestResponderNode:

    @patch("backend.app.agent.nodes._get_llm")
    def test_produces_answer_and_citations(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="Amazon S3 supports objects up to 5 TB."
        )
        mock_get_llm.return_value = mock_llm
        url = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html"
        state = _base_state(
            query="What is max S3 object size?",
            relevant_docs=[_mock_doc("S3 max 5TB", url)],
        )
        result = responder_node(state)
        assert "Amazon S3" in result["final_answer"]
        assert len(result["citations"]) == 1
        assert "docs.aws.amazon.com" in result["citations"][0]

    @patch("backend.app.agent.nodes._get_llm")
    def test_deduplicates_citations(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Answer.")
        mock_get_llm.return_value = mock_llm
        url = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html"
        state = _base_state(
            query="S3 limits?",
            relevant_docs=[_mock_doc("chunk 1", url), _mock_doc("chunk 2", url)],
        )
        result = responder_node(state)
        assert len(result["citations"]) == 1