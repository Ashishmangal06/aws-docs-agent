import logging
import pickle
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain.schema import BaseRetriever, Document
from langchain.callbacks.manager import CallbackManagerForRetrieverRun
from typing import List

from backend.app.rag.embeddings import get_embeddings
from backend.app.config import settings

logger = logging.getLogger(__name__)


class AWSDocsRetriever(BaseRetriever):
    """
    LangChain-compatible retriever backed by FAISS.
    Swap out the internals for OpenSearch Serverless in prod
    without changing any agent code.
    """

    vector_store: FAISS = None
    top_k: int = settings.top_k_results

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def load(cls) -> "AWSDocsRetriever":
        index_path = settings.vector_store_path
        if not index_path.exists():
            raise FileNotFoundError(
                f"FAISS index not found at {index_path}. "
                "Run `make ingest` first."
            )
        embeddings = get_embeddings()
        vector_store = FAISS.load_local(
            str(index_path),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        logger.info(f"FAISS index loaded from {index_path}")
        instance = cls()
        instance.vector_store = vector_store
        return instance

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        docs = self.vector_store.similarity_search(query, k=self.top_k)
        logger.info(f"Retrieved {len(docs)} chunks for query: '{query[:60]}...'")
        return docs