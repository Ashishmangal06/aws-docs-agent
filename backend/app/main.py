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
    logger.info("Starting up — pre-loading FAISS index...")
    try:
        import os
        import boto3 as _boto3
        from pathlib import Path

        bucket = os.getenv("VECTOR_STORE_BUCKET", "")
        local_path = Path(settings.vector_store_path)
        local_path.mkdir(parents=True, exist_ok=True)

        if bucket:
            logger.info(f"Downloading FAISS index from S3 bucket: {bucket}")
            s3 = _boto3.client("s3", region_name=settings.aws_region)
            for key_suffix in ["index.faiss", "index.pkl"]:
                s3_key = f"faiss_index/{key_suffix}"
                local_file = local_path / key_suffix
                logger.info(f"Downloading s3://{bucket}/{s3_key} → {local_file}")
                s3.download_file(bucket, s3_key, str(local_file))
            logger.info("S3 download complete.")
        else:
            logger.warning("VECTOR_STORE_BUCKET not set — skipping S3 download.")

        from backend.app.agent.nodes import _get_retriever
        _get_retriever()
        logger.info("FAISS index loaded and ready.")

    except Exception as e:
        logger.warning(
            f"FAISS index could not be loaded ({e}). "
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