import json
import uuid
import httpx
import streamlit as st
 
st.set_page_config(
    page_title="AWS Docs Agent",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
import os
from dotenv import load_dotenv
load_dotenv()
 
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
CHAT_ENDPOINT = f"{BACKEND_URL}/api/v1/chat"
HISTORY_ENDPOINT = f"{BACKEND_URL}/api/v1/history"
HEALTH_ENDPOINT = f"{BACKEND_URL}/api/v1/health"
 
AWS_SERVICES = [
    "All Services",
    "Amazon S3",
    "AWS Lambda",
    "Amazon EC2",
    "AWS IAM",
    "Amazon RDS",
    "Amazon VPC",
    "Amazon DynamoDB",
    "Amazon ECS",
    "AWS CloudFormation",
]
 
SAMPLE_QUESTIONS = [
    "What are the S3 bucket limits and quotas?",
    "How does Lambda cold start work and how can I reduce it?",
    "Compare SQS Standard vs FIFO queues",
    "What IAM policy conditions can I use for S3?",
    "How do I set up VPC peering between two accounts?",
    "What is the maximum size of an RDS PostgreSQL instance?",
]

def _extract_service_from_url(url: str) -> str:
    """Extracts a readable service name from an AWS docs URL."""
    mapping = {
        "AmazonS3": "Amazon S3",
        "lambda": "AWS Lambda",
        "AWSEC2": "Amazon EC2",
        "IAM": "AWS IAM",
        "AmazonRDS": "Amazon RDS",
        "AmazonVPC": "Amazon VPC",
        "amazondynamodb": "Amazon DynamoDB",
        "AmazonECS": "Amazon ECS",
        "AWSCloudFormation": "CloudFormation",
    }
    for key, name in mapping.items():
        if key.lower() in url.lower():
            return name
    return "AWS Docs"
 
def init_session():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []  # [{role, content, citations}]
    if "backend_healthy" not in st.session_state:
        st.session_state.backend_healthy = None
 
init_session()
 
def check_backend_health() -> dict:
    try:
        resp = httpx.get(HEALTH_ENDPOINT, timeout=5.0)
        return resp.json()
    except Exception:
        return {"status": "unreachable"}
 
def stream_response(user_message: str, session_id: str):
    """
    Calls the backend /chat endpoint and streams the SSE response.
    Yields (event_type, content) tuples.
    """
    payload = {
        "message": user_message,
        "session_id": session_id,
    }
 
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", CHAT_ENDPOINT, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    raw = line[6:]  # strip "data: " prefix
                    try:
                        event = json.loads(raw)
                        yield event["type"], event["content"]
                    except json.JSONDecodeError:
                        continue
 
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #232F3E 0%, #FF9900 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
    .main-header p { margin: 0.3rem 0 0 0; opacity: 0.85; font-size: 0.95rem; }
 
    .user-message {
        background: #f0f2f6;
        border-radius: 12px 12px 4px 12px;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
    }
    .assistant-message {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 12px 12px 12px 4px;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
    }
 
    .citation-pill {
        display: inline-block;
        background: #e8f4fd;
        border: 1px solid #bee3f8;
        color: #2b6cb0;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 0.78rem;
        margin: 2px 3px;
        text-decoration: none;
    }
 
    .status-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-ok { background: #c6f6d5; color: #276749; }
    .status-error { background: #fed7d7; color: #9b2335; }
 
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)
 
with st.sidebar:
    st.markdown("## ☁️ AWS Docs Agent")
    st.markdown("---")
 
    if st.button("🔄 Check Backend", use_container_width=True):
        health = check_backend_health()
        st.session_state.backend_healthy = health
 
    health = st.session_state.backend_healthy
    if health:
        if health.get("status") == "ok":
            index_status = "✅ Loaded" if health.get("faiss_index_loaded") else "⚠️ Not loaded"
            st.success(f"Backend: Online  |  Index: {index_status}")
        else:
            st.error("Backend: Unreachable")
 
    st.markdown("---")
 
    st.markdown("### 🔍 Service Filter")
    selected_service = st.selectbox(
        "Focus on a specific service:",
        AWS_SERVICES,
        index=0,
        label_visibility="collapsed",
    )
 
    st.markdown("---")
 
    st.markdown("### 💡 Sample Questions")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, key=f"sample_{q[:20]}", use_container_width=True):
            st.session_state.pending_message = q
 
    st.markdown("---")
 
    st.markdown("### ⚙️ Session")
    st.caption(f"Session ID: `{st.session_state.session_id[:16]}...`")
 
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            try:
                httpx.delete(
                    f"{HISTORY_ENDPOINT}/{st.session_state.session_id}",
                    timeout=3.0
                )
            except Exception:
                pass
            st.rerun()
    with col2:
        if st.button("🆕 New Session", use_container_width=True):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()
 
    st.markdown("---")
    st.caption("Built with LangGraph + AWS Bedrock + FAISS")
 
st.markdown("""
<div class="main-header">
    <h1>☁️ AWS Documentation Assistant</h1>
    <p>Ask anything about AWS services — powered by RAG + Agentic AI</p>
</div>
""", unsafe_allow_html=True)
 
chat_container = st.container()
 
with chat_container:
    if not st.session_state.messages:
        st.markdown("""
        <div style="text-align:center; padding: 3rem 1rem; color: #888;">
            <h3>👋 Welcome!</h3>
            <p>Ask a question about any AWS service, or pick a sample from the sidebar.</p>
        </div>
        """, unsafe_allow_html=True)
 
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="☁️"):
                st.markdown(msg["content"])
                if msg.get("citations"):
                    with st.expander(
                        f"📚 Sources ({len(msg['citations'])} references)",
                        expanded=False
                    ):
                        for url in msg["citations"]:
                            service = _extract_service_from_url(url)
                            st.markdown(
                                f"🔗 **{service}** — [{url}]({url})",
                                unsafe_allow_html=True
                            )
 
if "pending_message" in st.session_state:
    pending = st.session_state.pop("pending_message")
    st.session_state.user_input_override = pending
 
service_prefix = ""
if selected_service != "All Services":
    service_prefix = f"[Regarding {selected_service}] "
 
user_input = st.chat_input(
    placeholder="Ask about any AWS service... e.g. 'How does Lambda scaling work?'"
)
if "user_input_override" in st.session_state:
    user_input = st.session_state.pop("user_input_override")
 
if user_input:
    full_query = f"{service_prefix}{user_input}".strip()
 
    st.session_state.messages.append({
        "role": "user",
        "content": user_input,
        "citations": [],
    })
 
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_input)
 
    with st.chat_message("assistant", avatar="☁️"):
        status_placeholder = st.empty()
        answer_placeholder = st.empty()
        citations_data = []
        full_answer = ""
 
        try:
            for event_type, content in stream_response(
                full_query,
                st.session_state.session_id
            ):
                if event_type == "status":
                    status_placeholder.caption(f"⏳ {content}")
 
                elif event_type == "token":
                    full_answer += content
                    answer_placeholder.markdown(full_answer + "▌")
 
                elif event_type == "citation":
                    citations_data = content
 
                elif event_type == "done":
                    status_placeholder.empty()
                    answer_placeholder.markdown(full_answer)
 
                elif event_type == "error":
                    status_placeholder.empty()
                    answer_placeholder.error(f"⚠️ Error: {content}")
                    full_answer = f"Error: {content}"
 
            if citations_data:
                with st.expander(
                    f"📚 Sources ({len(citations_data)} references)",
                    expanded=False
                ):
                    for url in citations_data:
                        service = _extract_service_from_url(url)
                        st.markdown(f"🔗 **{service}** — [{url}]({url})")
 
        except httpx.ConnectError:
            status_placeholder.empty()
            answer_placeholder.error(
                "⚠️ Cannot connect to backend. "
                "Make sure the backend is running on port 8000."
            )
            full_answer = "Backend connection failed."
 
        except Exception as e:
            status_placeholder.empty()
            answer_placeholder.error(f"⚠️ Unexpected error: {e}")
            full_answer = f"Unexpected error: {e}"
 
    st.session_state.messages.append({
        "role": "assistant",
        "content": full_answer,
        "citations": citations_data,
    })