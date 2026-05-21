from typing import TypedDict, List, Annotated
from langchain.schema import BaseMessage, Document
import operator


class AgentState(TypedDict):
    # Conversation
    messages: Annotated[List[BaseMessage], operator.add]  # append-only
    session_id: str

    # Query handling
    query: str                    # original user query
    rewritten_query: str          # after query rewriter node

    # RAG
    retrieved_docs: List[Document]
    relevant_docs: List[Document]  # after grader filters

    # Output
    final_answer: str
    citations: List[str]

    # Control flow
    iterations: int               # guard against infinite loops
    should_retrieve_live: bool    # fallback to live fetch if grader rejects all