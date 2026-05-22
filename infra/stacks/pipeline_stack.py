import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_codebuild as codebuild,
    aws_ecr as ecr,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class PipelineStack(Stack):
    """
    Provisions:
    - ECR repository for the backend Docker image
    - CodeBuild project that builds and pushes the image
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ECR Repository
        self.ecr_repo = ecr.Repository(
            self,
            "BackendRepo",
            repository_name="aws-docs-agent-backend",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_images=True,
        )

        # CodeBuild role
        build_role = iam.Role(
            self,
            "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )

        self.ecr_repo.grant_pull_push(build_role)

        # CodeBuild project
        self.build_project = codebuild.Project(
            self,
            "BackendBuildProject",
            project_name="aws-docs-agent-build",
            role=build_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,  # required for Docker builds
            ),
            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=self.account
                ),
                "AWS_REGION": codebuild.BuildEnvironmentVariable(
                    value=self.region
                ),
                "ECR_REPO_URI": codebuild.BuildEnvironmentVariable(
                    value=self.ecr_repo.repository_uri
                ),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "echo Logging into ECR...",
                            "aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com",
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Building Docker image...",
                            "docker build -t aws-docs-agent-backend -f backend/Dockerfile .",
                            "docker tag aws-docs-agent-backend:latest $ECR_REPO_URI:latest",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Pushing image to ECR...",
                            "docker push $ECR_REPO_URI:latest",
                            "echo Build complete.",
                        ]
                    },
                },
            }),
            source=codebuild.Source.git_hub(
                owner="Ashishmangal06",        
                repo="aws-docs-agent",
                branch_or_ref="main",
            ),
        )

        CfnOutput(self, "ECRRepoURI", value=self.ecr_repo.repository_uri)
        CfnOutput(self, "BuildProjectName", value=self.build_project.project_name)

        # Frontend ECR repo
        self.frontend_ecr_repo = ecr.Repository(
            self,
            "FrontendRepo",
            repository_name="aws-docs-agent-frontend",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_images=True,
        )
        self.frontend_ecr_repo.grant_pull_push(build_role)

        # Frontend CodeBuild project
        self.frontend_build_project = codebuild.Project(
            self,
            "FrontendBuildProject",
            project_name="aws-docs-agent-frontend-build",
            role=build_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=self.account),
                "AWS_REGION": codebuild.BuildEnvironmentVariable(value=self.region),
                "ECR_REPO_URI": codebuild.BuildEnvironmentVariable(
                    value=self.frontend_ecr_repo.repository_uri
                ),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com",
                        ]
                    },
                    "build": {
                        "commands": [
                            "docker build -t aws-docs-agent-frontend -f frontend/Dockerfile .",
                            "docker tag aws-docs-agent-frontend:latest $ECR_REPO_URI:latest",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "docker push $ECR_REPO_URI:latest",
                        ]
                    },
                },
            }),
            source=codebuild.Source.git_hub(
                owner="Ashishmangal06",
                repo="aws-docs-agent",
                branch_or_ref="main",
            ),
        )

        CfnOutput(self, "FrontendECRRepoURI", value=self.frontend_ecr_repo.repository_uri)
        CfnOutput(self, "FrontendBuildProjectName", value=self.frontend_build_project.project_name)