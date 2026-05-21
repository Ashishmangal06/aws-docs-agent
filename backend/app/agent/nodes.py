import json
import logging
from typing import Any
import boto3
from langchain_aws import ChatBedrock
from langchain.schema import HumanMessage, AIMessage, SystemMessage

from backend.app.agent.state import AgentState
from backend.app.agent.tools import fetch_live_aws_doc
from backend.app.rag.retriever import AWSDocsRetriever
from backend.app.prompts import (
    SYSTEM_PROMPT,
    QUERY_REWRITER_PROMPT,
    GRADER_PROMPT,
)
from backend.app.config import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Shared LLM client (reused across nodes)
# --------------------------------------------------------------------------- #

def _get_llm(streaming: bool = False) -> ChatBedrock:
    session = boto3.Session(
        region_name=settings.aws_region,
        profile_name=settings.aws_profile,
    )
    return ChatBedrock(
        client=session.client("bedrock-runtime"),
        model_id=settings.bedrock_model_id,
        streaming=streaming,
        model_kwargs={"temperature": 0.2, "max_tokens": 2048},
    )


# Lazy-loaded retriever (loaded once at first use)
_retriever: AWSDocsRetriever | None = None

def _get_retriever() -> AWSDocsRetriever:
    global _retriever
    if _retriever is None:
        _retriever = AWSDocsRetriever.load()
    return _retriever


# --------------------------------------------------------------------------- #
# Node 1 — Query Rewriter
# --------------------------------------------------------------------------- #

def query_rewriter_node(state: AgentState) -> dict[str, Any]:
    """
    Rewrites the user's query for better retrieval.
    Skips rewriting if query is already specific (< 3 words = too short to rewrite).
    """
    query = state["query"]

    # Skip rewrite for very short, precise queries
    if len(query.split()) <= 3:
        logger.info(f"Query rewrite skipped (short query): '{query}'")
        return {"rewritten_query": query, "iterations": state.get("iterations", 0) + 1}

    # Build chat history string for context
    history = state.get("messages", [])
    history_str = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in history[-6:]  # last 3 turns
    )

    llm = _get_llm()
    prompt = QUERY_REWRITER_PROMPT.format(
        chat_history=history_str or "No prior conversation.",
        query=query,
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    rewritten = response.content.strip()

    logger.info(f"Query rewritten: '{query}' → '{rewritten}'")
    return {
        "rewritten_query": rewritten,
        "iterations": state.get("iterations", 0) + 1,
    }


# --------------------------------------------------------------------------- #
# Node 2 — Retriever
# --------------------------------------------------------------------------- #

def retriever_node(state: AgentState) -> dict[str, Any]:
    """
    Retrieves top-k chunks from FAISS using the rewritten query.
    """
    query = state.get("rewritten_query") or state["query"]
    retriever = _get_retriever()
    docs = retriever._get_relevant_documents(query, run_manager=None)

    logger.info(f"Retriever returned {len(docs)} docs for: '{query}'")
    return {"retrieved_docs": docs}


# --------------------------------------------------------------------------- #
# Node 3 — Grader
# --------------------------------------------------------------------------- #

def grader_node(state: AgentState) -> dict[str, Any]:
    """
    Grades each retrieved doc for relevance.
    If none are relevant, sets should_retrieve_live=True to trigger fallback.
    """
    query = state.get("rewritten_query") or state["query"]
    docs = state.get("retrieved_docs", [])
    llm = _get_llm()
    relevant_docs = []

    for doc in docs:
        prompt = GRADER_PROMPT.format(
            query=query,
            document=doc.page_content[:800],  # grade on first 800 chars
        )
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            result = json.loads(response.content.strip())
            if result.get("relevant"):
                relevant_docs.append(doc)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Grader failed for a doc: {e} — including it by default")
            relevant_docs.append(doc)  # fail open

    logger.info(f"Grader: {len(relevant_docs)}/{len(docs)} docs passed")

    should_live = len(relevant_docs) == 0
    if should_live:
        logger.info("No relevant docs found — flagging for live fetch fallback")

    return {
        "relevant_docs": relevant_docs,
        "should_retrieve_live": should_live,
    }


# --------------------------------------------------------------------------- #
# Node 4 — Live Fetcher (fallback)
# --------------------------------------------------------------------------- #

def live_fetcher_node(state: AgentState) -> dict[str, Any]:
    """
    Fallback: constructs a likely AWS docs URL from the query
    and fetches it live. Used when FAISS has no relevant results.
    """
    query = state.get("rewritten_query") or state["query"]

    # Ask the LLM to suggest the most likely AWS docs URL for this query
    llm = _get_llm()
    url_prompt = f"""Given this AWS-related query: "{query}"

Suggest the single most relevant AWS documentation URL from docs.aws.amazon.com.
Return ONLY the URL, nothing else. If unsure, return:
https://docs.aws.amazon.com/index.html"""

    response = llm.invoke([HumanMessage(content=url_prompt)])
    url = response.content.strip()

    logger.info(f"Live fetcher targeting URL: {url}")
    doc = fetch_live_aws_doc.invoke({"url": url})

    return {"relevant_docs": [doc], "should_retrieve_live": False}


# --------------------------------------------------------------------------- #
# Node 5 — Responder
# --------------------------------------------------------------------------- #

def responder_node(state: AgentState) -> dict[str, Any]:
    """
    Final node: synthesizes relevant docs into a grounded answer with citations.
    """
    query = state["query"]
    docs = state.get("relevant_docs") or state.get("retrieved_docs", [])

    # Build context string with source labels
    context_parts = []
    for i, doc in enumerate(docs):
        url = doc.metadata.get("source_url", "unknown")
        title = doc.metadata.get("page_title", "AWS Docs")
        context_parts.append(
            f"--- Source {i+1}: {title}\nURL: {url}\n\n{doc.page_content}"
        )
    context = "\n\n".join(context_parts) if context_parts else "No context available."

    # Build message list for LLM
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(context=context))
    history = state.get("messages", [])
    user_msg = HumanMessage(content=query)

    messages = [system_msg] + history[-4:] + [user_msg]

    llm = _get_llm(streaming=False)
    response = llm.invoke(messages)
    answer = response.content.strip()

    # Extract citations
    citations = list({
        doc.metadata["source_url"]
        for doc in docs
        if doc.metadata.get("source_url")
    })

    logger.info(f"Responder generated answer ({len(answer)} chars), {len(citations)} citations")

    return {
        "final_answer": answer,
        "citations": citations,
        "messages": [HumanMessage(content=query), AIMessage(content=answer)],
    }