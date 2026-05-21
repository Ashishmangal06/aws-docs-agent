import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain.schema import HumanMessage, AIMessage
from pydantic import BaseModel

from backend.app.agent import agent_graph
from backend.app.agent.state import AgentState
from backend.app.session import SessionStore

logger = logging.getLogger(__name__)
router = APIRouter()

# --------------------------------------------------------------------------- #
# Request / Response Models
# --------------------------------------------------------------------------- #

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None   # if None, a new session is created


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[str]


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


# --------------------------------------------------------------------------- #
# SSE Stream Helper
# --------------------------------------------------------------------------- #

async def _stream_agent_response(
    query: str,
    session_id: str,
) -> AsyncIterator[str]:
    """
    Runs the LangGraph agent and streams output as SSE events.

    Event types:
      - data: {"type": "token",    "content": "..."}
      - data: {"type": "status",   "content": "Retrieving docs..."}
      - data: {"type": "citation", "content": ["url1", "url2"]}
      - data: {"type": "done",     "content": ""}
      - data: {"type": "error",    "content": "error message"}
    """

    def _sse(event_type: str, content) -> str:
        payload = json.dumps({"type": event_type, "content": content})
        return f"data: {payload}\n\n"

    try:
        # Fetch existing session history
        history = SessionStore.get_history(session_id)

        # Build initial state
        initial_state: AgentState = {
            "messages": history,
            "session_id": session_id,
            "query": query,
            "rewritten_query": "",
            "retrieved_docs": [],
            "relevant_docs": [],
            "final_answer": "",
            "citations": [],
            "iterations": 0,
            "should_retrieve_live": False,
        }

        # Stream status events as the graph runs through nodes
        yield _sse("status", "Analyzing your question...")
        await asyncio.sleep(0)

        # Run the graph (synchronous internally — run in thread pool)
        loop = asyncio.get_event_loop()

        final_state: AgentState = await loop.run_in_executor(
            None,
            lambda: agent_graph.invoke(initial_state),
        )

        answer = final_state.get("final_answer", "")
        citations = final_state.get("citations", [])

        # Stream the answer token-by-token for a typewriter effect
        yield _sse("status", "Generating answer...")
        await asyncio.sleep(0)

        # Simulate streaming by chunking the final answer
        # (swap this for true streaming when LangGraph supports it natively)
        words = answer.split(" ")
        chunk_size = 5
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size]) + " "
            yield _sse("token", chunk)
            await asyncio.sleep(0.02)  # small delay for typewriter effect

        # Send citations
        if citations:
            yield _sse("citation", citations)

        # Persist to session store
        SessionStore.add_turn(
            session_id=session_id,
            user_message=query,
            assistant_message=answer,
        )

        yield _sse("done", "")

    except Exception as e:
        logger.exception(f"Agent error for session {session_id}: {e}")
        yield _sse("error", str(e))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Returns a streaming SSE response.
    Creates a new session if session_id is not provided.
    """
    session_id = request.session_id or str(uuid.uuid4())
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 chars).")

    logger.info(f"[{session_id}] Received: '{message[:80]}...'")

    return StreamingResponse(
        _stream_agent_response(message, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",       # disables nginx buffering
            "X-Session-Id": session_id,
        },
    )


@router.get("/health")
async def health():
    """Health check endpoint for load balancer / ECS."""
    from backend.app.agent.nodes import _retriever
    index_loaded = _retriever is not None
    return {
        "status": "ok",
        "version": "1.0.0",
        "faiss_index_loaded": index_loaded,
    }


@router.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Returns the conversation history for a session."""
    history = SessionStore.get_history(session_id)
    messages = [
        {
            "role": "user" if isinstance(m, HumanMessage) else "assistant",
            "content": m.content,
        }
        for m in history
    ]
    return HistoryResponse(session_id=session_id, messages=messages)


@router.delete("/history/{session_id}")
async def clear_history(session_id: str):
    """Clears the conversation history for a session."""
    SessionStore.clear(session_id)
    return {"status": "cleared", "session_id": session_id}