import sys
import logging
from pathlib import Path

# Make sure backend is on the path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.rag.ingestor import RAGIngestor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    logger = logging.getLogger("ingest_docs")
    logger.info("Starting AWS Docs ingestion pipeline...")

    ingestor = RAGIngestor()
    total_chunks = ingestor.run()

    logger.info(f"Ingestion complete. Total chunks in index: {total_chunks}")