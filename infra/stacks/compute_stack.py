import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
    CfnOutput,
    Duration,
)
from constructs import Construct
from aws_cdk import aws_ecr as ecr

class ComputeStack(Stack):
    """
    Provisions:
    - VPC (2 AZs, public + private subnets)
    - ECS Fargate cluster
    - Fargate service running the FastAPI backend
    - ALB with HTTP listener
    - IAM role with Bedrock + S3 + SSM permissions
    - CloudWatch log group
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vector_store_bucket: s3.Bucket,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------- #
        # VPC
        # ------------------------------------------------------------------- #
        vpc = ec2.Vpc(
            self,
            "AgentVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ------------------------------------------------------------------- #
        # ECS Cluster
        # ------------------------------------------------------------------- #
        cluster = ecs.Cluster(
            self,
            "AgentCluster",
            vpc=vpc,
            cluster_name="aws-docs-agent-cluster",
            container_insights=True,
        )

        # ------------------------------------------------------------------- #
        # IAM Task Role
        # ------------------------------------------------------------------- #
        task_role = iam.Role(
            self,
            "FargateTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for AWS Docs Agent Fargate task",
        )

        # Bedrock: invoke models
        task_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvokeModel",
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
                    f"arn:aws:bedrock:us-east-1:{self.account}:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                ],
            )
        )

        # S3: read vector index
        task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorStoreRead",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    vector_store_bucket.bucket_arn,
                    f"{vector_store_bucket.bucket_arn}/*",
                ],
            )
        )

        # SSM: read parameters
        task_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMReadParameters",
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter", "ssm:GetParametersByPath"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/aws-docs-agent/*"
                ],
            )
        )

        # ------------------------------------------------------------------- #
        # CloudWatch Log Group
        # ------------------------------------------------------------------- #
        log_group = logs.LogGroup(
            self,
            "AgentLogGroup",
            log_group_name="/ecs/aws-docs-agent",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------- #
        # Task Definition
        # ------------------------------------------------------------------- #
        task_definition = ecs.FargateTaskDefinition(
            self,
            "AgentTaskDef",
            cpu=2048,        # 2 vCPU — needed for FAISS in-memory index
            memory_limit_mib=8192,  # 8 GB — FAISS index can be large
            task_role=task_role,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        # ------------------------------------------------------------------- #
        # Container
        # ------------------------------------------------------------------- #
        container = task_definition.add_container(
            "BackendContainer",
            # Build from local Dockerfile
            # In CI/CD: replace with ecs.ContainerImage.from_ecr_repository(...)
            image=ecs.ContainerImage.from_ecr_repository(
                repository=ecr.Repository.from_repository_name(
                    self,
                    "BackendRepo",
                    repository_name="aws-docs-agent-backend",
                ),
                tag="latest",
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="backend",
                log_group=log_group,
            ),
            environment={
                "AWS_REGION": self.region,
                "LOG_LEVEL": "INFO",
                "VECTOR_STORE_PATH": "/app/data/faiss_index",
                "CORS_ORIGINS": '["*"]',  # tighten in prod
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/api/v1/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(10),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )

        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                protocol=ecs.Protocol.TCP,
            )
        )

        # ------------------------------------------------------------------- #
        # Fargate Service + ALB (using high-level pattern)
        # ------------------------------------------------------------------- #
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "AgentFargateService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=False,   # tasks in private subnet
            health_check_grace_period=Duration.seconds(90),
            service_name="aws-docs-agent-backend",
        )

        # ALB health check path
        fargate_service.target_group.configure_health_check(
            path="/api/v1/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )

        # ------------------------------------------------------------------- #
        # Auto Scaling
        # ------------------------------------------------------------------- #
        scalable_target = fargate_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=4,
        )

        scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(30),
        )

        # ------------------------------------------------------------------- #
        # Outputs
        # ------------------------------------------------------------------- #
        CfnOutput(
            self,
            "BackendURL",
            value=f"http://{fargate_service.load_balancer.load_balancer_dns_name}",
            export_name="BackendURL",
            description="ALB DNS name for the FastAPI backend",
        )

        CfnOutput(
            self,
            "ECSClusterName",
            value=cluster.cluster_name,
            export_name="ECSClusterName",
        )

        CfnOutput(
            self,
            "ECSServiceName",
            value=fargate_service.service.service_name,
            export_name="ECSServiceName",
        )

        # Expose ALB URL for frontend .env
        self.backend_url = f"http://{fargate_service.load_balancer.load_balancer_dns_name}"