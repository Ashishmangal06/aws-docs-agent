import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_ecr as ecr,
    aws_logs as logs,
    CfnOutput,
    Duration,
)
from constructs import Construct


class FrontendStack(Stack):
    """
    Provisions ECS Express (Fargate) service for Streamlit frontend.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        backend_url: str,
        vpc: ec2.Vpc = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # Reuse VPC from compute stack if provided, else create minimal one
        if vpc is None:
            vpc = ec2.Vpc(
                self,
                "FrontendVpc",
                max_azs=2,
                nat_gateways=1,
            )

        # ECS Cluster
        cluster = ecs.Cluster(
            self,
            "FrontendCluster",
            vpc=vpc,
            cluster_name="aws-docs-agent-frontend-cluster",
        )

        # ECR Repo for frontend image
        ecr_repo = ecr.Repository(
            self,
            "FrontendRepo",
            repository_name="aws-docs-agent-frontend",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_images=True,
        )

        # Log group
        log_group = logs.LogGroup(
            self,
            "FrontendLogGroup",
            log_group_name="/ecs/aws-docs-agent-frontend",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Task definition
        task_definition = ecs.FargateTaskDefinition(
            self,
            "FrontendTaskDef",
            cpu=512,
            memory_limit_mib=1024,
        )

        # Container
        container = task_definition.add_container(
            "FrontendContainer",
            image=ecs.ContainerImage.from_ecr_repository(
                repository=ecr_repo,
                tag="latest",
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="frontend",
                log_group=log_group,
            ),
            environment={
                "BACKEND_URL": backend_url,
            },
        )

        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8501,
                protocol=ecs.Protocol.TCP,
            )
        )

        # Fargate service + ALB
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "FrontendFargateService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=False,
            health_check_grace_period=Duration.seconds(120),
            service_name="aws-docs-agent-frontend",
        )

        fargate_service.target_group.configure_health_check(
            path="/_stcore/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )

        CfnOutput(
            self,
            "FrontendURL",
            value=f"http://{fargate_service.load_balancer.load_balancer_dns_name}",
            export_name="FrontendURL",
            description="Public URL for the Streamlit frontend",
        )

        self.frontend_url = f"http://{fargate_service.load_balancer.load_balancer_dns_name}"
        self.ecr_repo = ecr_repo