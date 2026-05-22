#!/usr/bin/env python3
import os
import aws_cdk as cdk
from dotenv import load_dotenv
from stacks import StorageStack, ComputeStack, NetworkStack, PipelineStack, FrontendStack

load_dotenv()

app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT") or os.environ["AWS_ACCOUNT_ID"],
    region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
)

tags = {
    "Project": "aws-docs-agent",
    "Environment": "prod",
    "ManagedBy": "CDK",
}

storage_stack = StorageStack(
    app, "AwsDocsAgentStorageStack", env=env, tags=tags
)

pipeline_stack = PipelineStack(
    app, "AwsDocsAgentPipelineStack", env=env, tags=tags
)

compute_stack = ComputeStack(
    app, "AwsDocsAgentComputeStack",
    vector_store_bucket=storage_stack.vector_store_bucket,
    env=env, tags=tags,
)

frontend_stack = FrontendStack(
    app, "AwsDocsAgentFrontendStack",
    backend_url=compute_stack.backend_url,
    env=env, tags=tags,
)

compute_stack.add_dependency(storage_stack)
compute_stack.add_dependency(pipeline_stack)
frontend_stack.add_dependency(compute_stack)

app.synth()