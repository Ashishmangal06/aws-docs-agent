import logging
import time
import pickle
import random
import xml.etree.ElementTree as ET
from typing import List

import httpx
from bs4 import BeautifulSoup
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_community.vectorstores import FAISS

from backend.app.rag.embeddings import get_embeddings
from backend.app.config import settings

logger = logging.getLogger(__name__)

# AWS services to ingest — expand this list as needed
AWS_DOC_SOURCES = {
    "s3":     "https://docs.aws.amazon.com/AmazonS3/latest/userguide/",
    "lambda": "https://docs.aws.amazon.com/lambda/latest/dg/",
    "ec2":    "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/",
    "iam":    "https://docs.aws.amazon.com/IAM/latest/UserGuide/",
    "rds":    "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/",
}

MAX_PAGES_PER_SERVICE = 30

# AWS docs are a React SPA — httpx gets a ~1 KB shell with 0 links when using
# a bot UA. Two fixes applied:
#   1. Use a real browser User-Agent so AWS returns fuller HTML.
#   2. Use sitemap.xml to discover URLs instead of crawling <a> tags,
#      since the nav is JS-rendered anyway.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Pages shorter than this are likely SPA shells with no real content
MIN_PAGE_BYTES = 2_000


class AWSDocsScraper:
    """
    Discovers AWS documentation URLs via sitemap.xml, then fetches and
    extracts clean text from each page.
    """

    def __init__(self):
        self.client = httpx.Client(
            headers={"User-Agent": BROWSER_UA},
            timeout=15.0,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # URL discovery
    # ------------------------------------------------------------------

    def _get_urls_from_sitemap(self, base_url: str) -> List[str]:
        """
        Fetch <base_url>sitemap.xml and return all <loc> URLs that live
        under base_url.  AWS sitemaps use an XML namespace, so we strip
        the namespace prefix when matching tag names.

        Example sitemap URL:
          https://docs.aws.amazon.com/AmazonS3/latest/userguide/sitemap.xml
        """
        sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
        logger.info(f"Fetching sitemap: {sitemap_url}")

        try:
            resp = self.client.get(sitemap_url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Sitemap fetch failed ({sitemap_url}): {e}")
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            logger.warning(f"Sitemap XML parse error: {e}")
            return []

        # <loc> tags may be namespaced: {http://www.sitemaps.org/schemas/sitemap/0.9}loc
        urls = [
            elem.text.strip()
            for elem in root.iter()
            if elem.tag.endswith("loc") and elem.text and elem.text.strip().startswith(base_url)
        ]

        logger.info(f"Sitemap returned {len(urls)} URLs for {base_url}")
        return urls

    # ------------------------------------------------------------------
    # Page extraction
    # ------------------------------------------------------------------

    def _extract_text(self, url: str, service_name: str) -> Document | None:
        """
        Fetch a single page and return a LangChain Document with clean text.
        Returns None if the page is a JS shell, too short, or unreachable.
        """
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Skipping {url}: {e}")
            return None

        # SPA shell guard — real AWS doc pages are well over 10 KB
        if len(resp.text) < MIN_PAGE_BYTES:
            logger.debug(f"Skipping SPA shell ({len(resp.text)} bytes): {url}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Strip navigation chrome
        for tag in soup(["nav", "footer", "script", "style", "header"]):
            tag.decompose()

        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else url

        # AWS-specific content containers, falling back to <body>
        main = (
            soup.find("main")
            or soup.find("div", {"id": "main-content"})
            or soup.find("div", {"id": "aws-topic-content"})
            or soup.body
        )
        if not main:
            return None

        text = main.get_text(separator="\n", strip=True)

        if len(text) < 200:
            return None

        return Document(
            page_content=text,
            metadata={
                "source_url": url,
                "service_name": service_name,
                "page_title": title,
            },
        )

    # ------------------------------------------------------------------
    # Per-service entry point
    # ------------------------------------------------------------------

    def scrape_service(self, service_name: str, base_url: str) -> List[Document]:
        """
        Discover URLs via sitemap, sample up to MAX_PAGES_PER_SERVICE,
        and return extracted Documents.
        """
        logger.info(f"[{service_name}] Starting scrape — base: {base_url}")

        urls = self._get_urls_from_sitemap(base_url)
        if not urls:
            logger.warning(
                f"[{service_name}] No URLs found in sitemap. "
                f"Verify manually: {base_url.rstrip('/')}/sitemap.xml"
            )
            return []

        # Shuffle so repeated runs sample different pages
        random.shuffle(urls)
        urls = urls[:MAX_PAGES_PER_SERVICE]

        documents: List[Document] = []
        for url in urls:
            doc = self._extract_text(url, service_name)
            if doc:
                documents.append(doc)
                logger.info(f"  [{service_name}] ✓ {doc.metadata['page_title']}")
            time.sleep(0.3)  # be polite

        logger.info(f"[{service_name}] Pages scraped: {len(documents)}/{len(urls)} attempted")
        return documents


class RAGIngestor:
    """
    Orchestrates scraping → chunking → embedding → FAISS index creation.
    """

    def __init__(self):
        self.scraper = AWSDocsScraper()
        self.embeddings = get_embeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def _chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents into chunks, preserving and extending metadata."""
        chunks: List[Document] = []
        for doc in documents:
            splits = self.text_splitter.split_documents([doc])
            for i, chunk in enumerate(splits):
                chunk.metadata["chunk_index"] = i
            chunks.extend(splits)
        logger.info(f"Total chunks created: {len(chunks)}")
        return chunks

    def run(self) -> int:
        """Full pipeline: scrape → chunk → embed → save FAISS index."""

        # Step 1: Scrape
        all_documents: List[Document] = []
        for service_name, base_url in AWS_DOC_SOURCES.items():
            docs = self.scraper.scrape_service(service_name, base_url)
            all_documents.extend(docs)
        logger.info(f"Total raw pages collected: {len(all_documents)}")

        # Step 2: Chunk
        chunks = self._chunk_documents(all_documents)

        # Guard: nothing to index
        if not chunks:
            logger.error(
                "No chunks produced — scraping returned 0 documents. "
                "Check network access to docs.aws.amazon.com and that sitemaps are reachable."
            )
            return 0

        logger.info(f"First chunk preview: {chunks[0].page_content[:200]}")

        # Step 3: Embed + build FAISS index
        logger.info("Building FAISS index... (this may take a few minutes)")
        test_embedding = self.embeddings.embed_query("hello world")
        logger.info(f"Embedding dimension: {len(test_embedding)}")
        vector_store = FAISS.from_documents(chunks, self.embeddings)

        # Step 4: Persist index
        output_path = settings.vector_store_path
        output_path.mkdir(parents=True, exist_ok=True)
        vector_store.save_local(str(output_path))
        logger.info(f"FAISS index saved to: {output_path}")

        # Step 5: Persist metadata for citation lookup
        metadata_path = output_path / "metadata.pkl"
        with open(metadata_path, "wb") as f:
            pickle.dump([chunk.metadata for chunk in chunks], f)

        logger.info(f"Chunks indexed: {len(chunks)}")
        return len(chunks)