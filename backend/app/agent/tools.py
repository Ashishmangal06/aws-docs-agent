import logging
import httpx
from bs4 import BeautifulSoup
from langchain.tools import tool
from langchain.schema import Document

logger = logging.getLogger(__name__)


@tool
def rewrite_query(query: str, chat_history: str = "") -> str:
    """
    Rewrites a vague or multi-part user query into a focused,
    searchable AWS documentation query.
    Use this when the query is ambiguous or too broad.
    """
    # This tool's logic is handled inside the rewriter node via direct LLM call
    # Keeping it as a tool so LangGraph can route to it explicitly
    return query


@tool
def fetch_live_aws_doc(url: str) -> Document:
    """
    Fetches a specific AWS documentation page live from the web.
    Use this as a fallback when the FAISS index does not have
    relevant results for the user's query.
    The URL must be a valid docs.aws.amazon.com URL.
    """
    if "docs.aws.amazon.com" not in url:
        return Document(
            page_content="Invalid URL. Only docs.aws.amazon.com URLs are allowed.",
            metadata={"source_url": url, "service_name": "unknown", "page_title": "Error"},
        )

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "aws-docs-agent-bot/1.0"}
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Live fetch failed for {url}: {e}")
        return Document(
            page_content=f"Failed to fetch page: {e}",
            metadata={"source_url": url, "service_name": "unknown", "page_title": "Error"},
        )

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["nav", "footer", "script", "style", "header"]):
        tag.decompose()

    title = soup.find("h1")
    title_text = title.get_text(strip=True) if title else url
    main = soup.find("main") or soup.find("div", {"id": "main-content"}) or soup.body
    text = main.get_text(separator="\n", strip=True) if main else ""

    logger.info(f"Live fetched: {title_text} from {url}")

    return Document(
        page_content=text[:4000],  # cap to avoid context overflow
        metadata={
            "source_url": url,
            "service_name": "live-fetch",
            "page_title": title_text,
        },
    )