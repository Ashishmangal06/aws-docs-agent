import logging
import boto3
from langchain_aws import BedrockEmbeddings
from backend.app.config import settings

logger = logging.getLogger(__name__)

def get_embeddings() -> BedrockEmbeddings:
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",  # hardcoded — don't rely on env
    )
    embeddings = BedrockEmbeddings(
        client=bedrock_client,
        model_id=settings.bedrock_embeddings_model_id,
    )
    return embeddings