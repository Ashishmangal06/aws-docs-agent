import aws_cdk as cdk
from aws_cdk.assertions import Template
from infra.stacks import StorageStack, ComputeStack


def test_storage_stack_creates_bucket():
    app = cdk.App()
    stack = StorageStack(app, "TestStorageStack")
    template = Template.from_stack(stack)

    template.has_resource_properties("AWS::S3::Bucket", {
        "VersioningConfiguration": {"Status": "Enabled"},
        "BucketEncryption": {
            "ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        },
    })


def test_storage_stack_creates_ssm_parameters():
    app = cdk.App()
    stack = StorageStack(app, "TestStorageStack2")
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::SSM::Parameter", 4)


def test_compute_stack_creates_fargate_service():
    app = cdk.App()
    from aws_cdk import aws_s3 as s3
    storage = StorageStack(app, "TestStorage3")
    compute = ComputeStack(
        app,
        "TestComputeStack",
        vector_store_bucket=storage.vector_store_bucket,
    )
    template = Template.from_stack(compute)

    template.resource_count_is("AWS::ECS::Cluster", 1)
    template.resource_count_is("AWS::ECS::TaskDefinition", 1)
    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "2048",
        "Memory": "8192",
    })