"""Long-lived resources GitHub Actions needs before the application stack can deploy."""

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from constructs import Construct

from incidentflow_cdk.names import (
    DEPLOY_ROLE_NAME,
    GITHUB_DEPLOY_SUBJECT,
    GITHUB_OIDC_URL,
    MIGRATE_FUNCTION_NAME,
    REPOSITORY_NAME,
    web_bucket_name,
)

_GITHUB_TOKEN_HOST = GITHUB_OIDC_URL.removeprefix("https://")
_STS_AUDIENCE = "sts.amazonaws.com"


class GithubDeployStack(Stack):
    """The image repository, the GitHub OIDC provider, and the role the deploy workflow assumes.

    The account may hold only one provider for the GitHub issuer; if one already exists this
    stack fails to create its own and the setup guide explains the way out.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # CI pushes `api-<sha>` and `jobs-<sha>` here before the application stack deploys.
        repository = ecr.Repository(
            self,
            "Repository",
            repository_name=REPOSITORY_NAME,
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(description="Keep the last 10 images", max_image_count=10)
            ],
        )
        # The functions live in another stack, which cannot add a policy to this repository.
        repository.add_to_resource_policy(
            iam.PolicyStatement(
                sid="LambdaPull",
                principals=[iam.ServicePrincipal("lambda.amazonaws.com")],
                actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                conditions={
                    "StringLike": {
                        "aws:sourceArn": f"arn:aws:lambda:{self.region}:{self.account}:function:*"
                    }
                },
            )
        )

        provider = iam.OidcProviderNative(
            self, "GithubOidcProvider", url=GITHUB_OIDC_URL, client_ids=[_STS_AUDIENCE]
        )
        role = iam.Role(
            self,
            "DeployRole",
            role_name=DEPLOY_ROLE_NAME,
            description="Assumed by GitHub Actions on master to deploy IncidentFlow.",
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{_GITHUB_TOKEN_HOST}:aud": _STS_AUDIENCE,
                        f"{_GITHUB_TOKEN_HOST}:sub": GITHUB_DEPLOY_SUBJECT,
                    }
                },
            ),
        )
        self._grant_deploy(role, repository)

        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
        CfnOutput(self, "RepositoryUri", value=repository.repository_uri)

    def _grant_deploy(self, role: iam.Role, repository: ecr.Repository) -> None:
        account, region = self.account, self.region
        bucket = web_bucket_name(account)
        # `cdk deploy` does the CloudFormation work through the bootstrap roles.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{account}:role/cdk-hnb659fds-*-role-{account}-{region}"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"])
        )
        repository.grant_pull_push(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{region}:{account}:function:{MIGRATE_FUNCTION_NAME}"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[f"arn:aws:s3:::{bucket}"])
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[f"arn:aws:s3:::{bucket}/*"],
            )
        )
        # The distribution id is generated, so invalidation is scoped to the account's
        # distributions; the owner's account holds only this one.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
                resources=[f"arn:aws:cloudfront::{account}:distribution/*"],
            )
        )
