from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path

class Settings(BaseSettings):
    # AWS
    aws_region: str = Field(default="us-east-1", env="AWS_REGION")
    aws_profile: str = Field(default="default", env="AWS_PROFILE")

    # Bedrock
    bedrock_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        env="BEDROCK_MODEL_ID"
    )
    bedrock_embeddings_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        env="BEDROCK_EMBEDDINGS_MODEL_ID"
    )

    # RAG
    vector_store_path: Path = Field(
        default=Path("./data/faiss_index"),
        env="VECTOR_STORE_PATH"
    )
    top_k_results: int = Field(default=5, env="TOP_K_RESULTS")
    chunk_size: int = Field(default=1000, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, env="CHUNK_OVERLAP")

    # App
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    cors_origins: list[str] = Field(
        default=["http://localhost:8501"],
        env="CORS_ORIGINS"
    )
    backend_url: str = Field(
        default="http://localhost:8000",
        env="BACKEND_URL"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()