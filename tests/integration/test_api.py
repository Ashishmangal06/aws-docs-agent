"""
Integration tests — require the backend to be running.
Uses the deployed ALB URL from environment variable.

Set before running:
    $env:BACKEND_URL = "http://your-alb-url"
    pytest tests/integration/ -v
"""

import json
import os
import uuid
import pytest
import httpx

BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000") + "/api/v1"
TIMEOUT = 120.0


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def client():
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)


@pytest.fixture(scope="module")
def session_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# SSE helper
# --------------------------------------------------------------------------- #

def collect_sse_events(client, message, session_id):
    result = {
        "tokens": [],
        "full_answer": "",
        "citations": [],
        "status_messages": [],
        "error": None,
        "done": False,
    }
    with client.stream(
        "POST", "/chat",
        json={"message": message, "session_id": session_id},
    ) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            content = event.get("content", "")
            if etype == "token":
                result["tokens"].append(content)
                result["full_answer"] += content
            elif etype == "citation":
                result["citations"] = content
            elif etype == "status":
                result["status_messages"].append(content)
            elif etype == "error":
                result["error"] = content
            elif etype == "done":
                result["done"] = True
    return result


# --------------------------------------------------------------------------- #
# Health check
# --------------------------------------------------------------------------- #

class TestHealth:

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "faiss_index_loaded" in data

    def test_faiss_index_loaded(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["faiss_index_loaded"] is True, \
            "FAISS index not loaded — check S3 upload and container restart"


# --------------------------------------------------------------------------- #
# Chat endpoint
# --------------------------------------------------------------------------- #

class TestChat:

    def test_streams_tokens(self, client, session_id):
        result = collect_sse_events(client, "What is Amazon S3?", session_id)
        assert result["done"] is True
        assert result["error"] is None
        assert len(result["tokens"]) > 0
        assert len(result["full_answer"]) > 100

    def test_returns_citations(self, client, session_id):
        result = collect_sse_events(
            client, "What are the S3 bucket limits?", session_id
        )
        assert result["done"] is True
        assert len(result["citations"]) > 0
        for url in result["citations"]:
            assert "aws.amazon.com" in url or url.startswith("http")

    def test_sends_status_events(self, client, session_id):
        result = collect_sse_events(
            client, "How does Lambda cold start work?", session_id
        )
        assert len(result["status_messages"]) > 0

    def test_answer_is_aws_relevant(self, client, session_id):
        result = collect_sse_events(
            client, "What is the maximum size of an S3 object?", session_id
        )
        answer_lower = result["full_answer"].lower()
        assert any(kw in answer_lower for kw in [
            "s3", "object", "5 tb", "5tb", "terabyte", "multipart"
        ])

    def test_empty_message_returns_400(self, client, session_id):
        resp = client.post("/chat", json={"message": "", "session_id": session_id})
        assert resp.status_code == 400

    def test_too_long_message_returns_400(self, client, session_id):
        resp = client.post(
            "/chat",
            json={"message": "x" * 2001, "session_id": session_id}
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Session / History
# --------------------------------------------------------------------------- #

class TestSession:

    def test_history_after_chat(self, client):
        sid = str(uuid.uuid4())
        collect_sse_events(client, "What is Amazon RDS?", sid)
        resp = client.get(f"/history/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) >= 2
        roles = [m["role"] for m in data["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_clear_history(self, client):
        sid = str(uuid.uuid4())
        collect_sse_events(client, "What is CloudFormation?", sid)
        resp = client.delete(f"/history/{sid}")
        assert resp.status_code == 200
        resp = client.get(f"/history/{sid}")
        assert resp.json()["messages"] == []

    def test_multi_turn_context(self, client):
        sid = str(uuid.uuid4())
        collect_sse_events(client, "What is Amazon S3?", sid)
        result = collect_sse_events(client, "What are its storage classes?", sid)
        answer_lower = result["full_answer"].lower()
        assert any(kw in answer_lower for kw in [
            "standard", "glacier", "intelligent", "storage class", "s3"
        ])


# --------------------------------------------------------------------------- #
# Agent behaviour
# --------------------------------------------------------------------------- #

class TestAgentBehaviour:

    def test_vague_query_still_answers(self, client, session_id):
        result = collect_sse_events(client, "how do I store files?", session_id)
        assert result["done"] is True
        assert len(result["full_answer"]) > 50
        assert result["error"] is None

    def test_specific_technical_query(self, client, session_id):
        result = collect_sse_events(
            client,
            "What is the maximum Lambda deployment package size?",
            session_id,
        )
        answer_lower = result["full_answer"].lower()
        assert any(kw in answer_lower for kw in [
            "250", "deployment", "lambda", "zip", "package"
        ])

    def test_non_aws_query_redirects(self, client, session_id):
        result = collect_sse_events(
            client, "What is the best pizza recipe?", session_id
        )
        answer_lower = result["full_answer"].lower()
        assert any(kw in answer_lower for kw in [
            "don't have", "not have", "aws", "documentation",
            "unable", "can't", "cannot", "outside"
        ])