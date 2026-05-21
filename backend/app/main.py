import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.api.routes import router
from backend.app.rag.retriever import AWSDocsRetriever
from backend.app.agent import agent_graph  # triggers graph compilation at startup

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: pre-load FAISS index into memory so first request isn't slow.
    Shutdown: clean up if needed.
    """
    logger.info("Starting up — pre-loading FAISS index...")
    try:
        from backend.app.agent.nodes import _get_retriever
        _get_retriever()
        logger.info("FAISS index loaded and ready.")
    except FileNotFoundError:
        logger.warning(
            "FAISS index not found. Run `make ingest` before serving. "
            "Live-fetch fallback will be used for all queries."
        )
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="AWS Docs Agent",
    description="Agentic RAG chatbot for AWS documentation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"status": "ok", "service": "aws-docs-agent"}