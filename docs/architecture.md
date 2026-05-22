# Architecture & Design Decisions

## System Overview

```
Browser → ALB → Streamlit (ECS Fargate)
                    ↓ SSE /chat
              ALB → FastAPI (ECS Fargate)
                    ↓
              LangGraph Agent
                    ↓
         ┌──────────────────────┐
         │  query_rewriter_node  │ Claude rewrites vague queries
         │  retriever_node       │ FAISS top-k similarity search
         │  grader_node          │ Relevance filter per chunk
         │  live_fetcher_node    │ Fallback: live AWS docs fetch
         │  responder_node       │ Claude synthesizes final answer
         └──────────────────────┘
                    ↓
              AWS Bedrock
         (Claude Sonnet 4 + Titan Embeddings v2)
```

---

## 1. Why LangGraph over a Simple Chain?

A naive RAG chain breaks down on real AWS questions:

- **Multi-part queries**: "How does Lambda scaling work and what are its VPC limitations?" needs decomposition
- **Poor retrieval**: Vague queries produce irrelevant chunks — the grader node catches this before the LLM hallucinates
- **Stale index**: Some AWS service limits change frequently — a live-fetch fallback keeps answers accurate

LangGraph gives us a stateful, cyclical graph where each node inspects the full `AgentState` and routing decisions are based on actual content.

```
query_rewriter → retriever → grader ──(relevant)──→ responder → END
                                    ↘(not relevant)→ live_fetcher ↗
```

---

## 2. RAG Pipeline Design

### Chunking Strategy

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Chunk size | 1000 tokens | Balances context richness vs embedding noise |
| Overlap | 200 tokens | Preserves context across chunk boundaries |
| Splitter | RecursiveCharacterTextSplitter | Respects paragraph → sentence → word hierarchy |

### Metadata Per Chunk

```python
{
    "source_url": "https://docs.aws.amazon.com/lambda/...",
    "service_name": "lambda",
    "page_title": "Lambda execution environment",
    "chunk_index": 3
}
```

Metadata is surfaced as citations in the UI — users always know where the answer came from.

### Embedding Model

**Amazon Titan Embeddings v2** — chosen because:
- Same AWS ecosystem, no external API keys
- Data never leaves AWS trust boundary
- Drop-in LangChain interface via `BedrockEmbeddings`

### FAISS → OpenSearch Upgrade Path

```python
# Dev (current): FAISS loaded from S3 at container startup
vector_store = FAISS.load_local(index_path, embeddings)

# Prod upgrade (swap internals, same interface):
vector_store = OpenSearchVectorSearch(
    opensearch_url=endpoint,
    index_name="aws-docs",
    embedding_function=embeddings,
)
```

Both are behind `AWSDocsRetriever(BaseRetriever)` — the agent never knows the difference.

---

## 3. Grader Node — Hallucination Prevention

Without the grader, the LLM receives whatever chunks FAISS returns — even loosely related ones. This causes hallucinated API parameters and fabricated service limits.

The grader sends each chunk to Claude with a strict binary prompt returning `{"relevant": true/false}`.

If all chunks fail → route to `live_fetcher_node` which fetches directly from `docs.aws.amazon.com`. The system degrades gracefully instead of hallucinating.

**Fail-open design**: if the grader itself errors, the chunk is kept by default. We prefer over-inclusive context over silent failure.

---

## 4. Streaming Architecture

```
POST /api/v1/chat → StreamingResponse (text/event-stream)
  → data: {"type": "status",   "content": "Analyzing..."}
  → data: {"type": "token",    "content": "Amazon S3 "}
  → data: {"type": "token",    "content": "supports up to "}
  → data: {"type": "citation", "content": ["https://..."]}
  → data: {"type": "done",     "content": ""}
```

LangGraph runs synchronously in a thread pool executor (`loop.run_in_executor`) so it doesn't block the async FastAPI event loop.

---

## 5. Session Memory Design

```python
# Current: in-memory dict (resets on container restart)
_store: dict[str, list[BaseMessage]] = defaultdict(list)

# Production upgrade (one line change):
from langchain_community.chat_message_histories import RedisChatMessageHistory
history = RedisChatMessageHistory(session_id=session_id, url=redis_url)
```

History trimmed to last 10 turns to prevent context window overflow.

---

## 6. Infrastructure Design

### Why ECS Fargate over Lambda?

| Concern | Lambda | Fargate |
|---------|--------|---------|
| FAISS index in memory | ❌ Cold start reloads index | ✅ Persistent across requests |
| SSE streaming | ⚠️ Needs Response Streaming | ✅ Native HTTP streaming |
| Long-running requests | ❌ 15 min max | ✅ No limit |
| Cost at low traffic | ✅ Pay-per-request | ⚠️ Always-on |

### IAM Least Privilege

```
bedrock:InvokeModel + InvokeModelWithResponseStream → all models (*)
s3:GetObject + s3:ListBucket                        → vector store bucket only
ssm:GetParameter                                    → /aws-docs-agent/* only
```

### CDK Stack Separation

| Stack | Purpose | Lifecycle |
|-------|---------|-----------|
| StorageStack | S3 bucket | RETAIN — never auto-deleted |
| PipelineStack | CodeBuild + ECR | Rebuild images independently |
| ComputeStack | Backend ECS + ALB | Redeploy without touching index |
| FrontendStack | Frontend ECS + ALB | Deploy UI independently |

---

## 7. Trade-offs & Known Limitations

| Area | Current | Production Path |
|------|---------|----------------|
| Vector store | FAISS on S3 | OpenSearch Serverless |
| Session store | In-memory | ElastiCache Redis |
| Ingestion | Manual CLI | EventBridge scheduled Lambda |
| Auth | None | Cognito + JWT |
| Doc coverage | 5 services × 30 pages | Full sitemap via Step Functions |
| HTTPS | HTTP only | ACM certificate + Route53 |