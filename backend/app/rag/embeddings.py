import logging
import boto3
from langchain_aws import BedrockEmbeddings
from backend.app.config import settings

logger = logging.getLogger(__name__)

def get_embeddings() -> BedrockEmbeddings:
    """
    Returns a LangChain-compatible Titan Embeddings client via Bedrock.
    """
    session = boto3.Session(
        region_name=settings.aws_region,
        profile_name=settings.aws_profile
    )
    bedrock_client = session.client("bedrock-runtime")

    embeddings = BedrockEmbeddings(
        client=bedrock_client,
        model_id=settings.bedrock_embeddings_model_id,
    )

    logger.info(f"Embeddings model loaded: {settings.bedrock_embeddings_model_id}")
    return embeddings