"""The IncidentFlow application: dashboard, sign-in, API, job queue, and the six Lambdas.

Dependency order (CloudFormation needs it acyclic): the app client's callback URL uses the
distribution's domain; the distribution's `/api/*` origin uses only the HTTP API resource; the
JWT authorizer and the route (separate resources) use the API and the app client. The cycle
"client -> distribution -> API -> authorizer -> client" therefore never closes.
"""

from dataclasses import dataclass
from typing import Any

from aws_cdk import CfnOutput, Duration, Fn, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from incidentflow_cdk.names import (
    MIGRATE_FUNCTION_NAME,
    REPOSITORY_NAME,
    SSM_PATH,
    web_bucket_name,
)

WORKER_TIMEOUT = Duration.seconds(900)
JOB_TIMEOUT_SECONDS = "780"
DEMO_ALARM_PREFIX = "if-"
BUDGET_USD = 10
BUDGET_THRESHOLDS = (50, 80, 100)

SPA_REWRITE_CODE = """\
function handler(event) {
  var request = event.request;
  var last = request.uri.split('/').pop();
  if (last.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
"""

_JOBS_ENTRYPOINT = ["python", "-m", "awslambdaric"]


@dataclass(frozen=True)
class IntegrationSettings:
    """Non-secret names the worker's integrations need (from `cdk.json` context)."""

    github_repositories: str
    cloudwatch_log_groups: str
    pinecone_index_name: str
    pinecone_namespace: str
    mongodb_database: str
    mongodb_events_collection: str

    def as_environment(self) -> dict[str, str]:
        return {
            "GITHUB_MCP_REPOSITORIES": self.github_repositories,
            "CLOUDWATCH_MCP_LOG_GROUPS": self.cloudwatch_log_groups,
            "PINECONE_INDEX_NAME": self.pinecone_index_name,
            "PINECONE_NAMESPACE": self.pinecone_namespace,
            "MONGODB_MCP_DATABASE": self.mongodb_database,
            "MONGODB_MCP_EVENTS_COLLECTION": self.mongodb_events_collection,
        }


class IncidentFlowStack(Stack):
    """AWS stack: API, worker, sweeper, demo and ingestion Lambdas, queue, web hosting."""
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        image_tag: str,
        budget_email: str | None,
        integration_settings: IntegrationSettings,
        ingest_alarm_prefix: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._repository = ecr.Repository.from_repository_name(self, "Repository", REPOSITORY_NAME)
        self._image_tag = image_tag

        dead_letters = sqs.Queue(
            self,
            "JobDeadLetterQueue",
            retention_period=Duration.days(14),
            enforce_ssl=True,
        )
        queue = sqs.Queue(
            self,
            "JobQueue",
            visibility_timeout=WORKER_TIMEOUT,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dead_letters),
        )
        token_table = dynamodb.Table(
            self,
            "JiraTokenTable",
            partition_key=dynamodb.Attribute(name="collection", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="key", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        bucket = s3.Bucket(
            self,
            "DashboardBucket",
            bucket_name=web_bucket_name(self.account),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        http_api = apigwv2.HttpApi(self, "HttpApi", description="IncidentFlow API")
        distribution = self._distribution(bucket, http_api)

        user_pool, client, domain = self._sign_in(distribution)
        issuer = Fn.join(
            "", [f"https://cognito-idp.{self.region}.amazonaws.com/", user_pool.user_pool_id]
        )

        demo = self._demo_function()

        api_function = self._function(
            "ApiFunction",
            image="api",
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "JOB_QUEUE_URL": queue.queue_url,
                "AUTH_ENABLED": "true",
                "OIDC_ISSUER_URL": issuer,
                "OIDC_CLIENT_ID": client.user_pool_client_id,
                "AWS_LWA_PORT": "8000",
                "AWS_LWA_READINESS_CHECK_PATH": "/health",
                "DEMO_ENABLED": "true",
                "DEMO_FUNCTION_NAME": demo.function_name,
            },
        )
        queue.grant_send_messages(api_function)
        api_function.add_to_role_policy(
            iam.PolicyStatement(actions=["lambda:InvokeFunction"], resources=[demo.function_arn])
        )
        http_api.add_routes(
            path="/api/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integrations.HttpLambdaIntegration("ApiIntegration", api_function),
            authorizer=authorizers.HttpJwtAuthorizer(
                "CognitoAuthorizer", issuer, jwt_audience=[client.user_pool_client_id]
            ),
        )

        worker = self._function(
            "WorkerFunction",
            image="jobs",
            handler="worker_handler",
            timeout=WORKER_TIMEOUT,
            memory_size=3008,
            environment={
                "JOB_QUEUE_URL": queue.queue_url,
                "JOB_TIMEOUT_SECONDS": JOB_TIMEOUT_SECONDS,
                "MCP_OAUTH_TOKEN_STORE": "dynamodb",
                "MCP_OAUTH_DYNAMODB_TABLE": token_table.table_name,
                "MONGODB_MCP_TRANSPORT": "stdio",
                "MDB_MCP_TELEMETRY": "disabled",
                "GITHUB_MCP_TRANSPORT": "http",
                "GITHUB_MCP_URL": "https://api.githubcopilot.com/mcp/",
                "CLOUDWATCH_MCP_COMMAND": "/opt/cloudwatch-mcp/bin/awslabs.cloudwatch-mcp-server",
                "CLOUDWATCH_MCP_COMMAND_ARGS": "",
                "JIRA_MCP_ENABLED": "true",
                "JIRA_MCP_WRITE_ENABLED": "true",
                "MONGODB_MCP_ENABLED": "true",
                "PINECONE_ENABLED": "true",
                "GITHUB_MCP_ENABLED": "true",
                "CLOUDWATCH_MCP_ENABLED": "true",
                **integration_settings.as_environment(),
            },
        )
        worker.add_event_source(
            event_sources.SqsEventSource(
                queue, batch_size=1, max_concurrency=2, report_batch_item_failures=True
            )
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:DescribeTable",
                    "dynamodb:DescribeTimeToLive",
                    "dynamodb:UpdateTimeToLive",
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:DeleteItem",
                ],
                resources=[token_table.table_arn],
            )
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:GetMetricData",
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:StopQuery",
                ],
                resources=["*"],
            )
        )

        sweeper = self._function(
            "SweeperFunction",
            image="jobs",
            handler="sweeper_handler",
            timeout=Duration.seconds(120),
            memory_size=512,
            environment={"JOB_QUEUE_URL": queue.queue_url},
        )
        queue.grant_send_messages(sweeper)
        events.Rule(
            self,
            "SweeperSchedule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[targets.LambdaFunction(sweeper)],
        )

        self._alarm_ingestion(ingest_alarm_prefix)

        migrate = self._function(
            "MigrateFunction",
            image="jobs",
            handler="migrate_handler",
            timeout=Duration.seconds(300),
            memory_size=1024,
            function_name=MIGRATE_FUNCTION_NAME,
            environment={},
        )

        self._budget(budget_email)

        CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "WebBucket", value=bucket.bucket_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=client.user_pool_client_id)
        CfnOutput(self, "CognitoDomain", value=domain.base_url())
        CfnOutput(self, "MigrateFunctionName", value=migrate.function_name)

    def _alarm_ingestion(self, alarm_prefix: str) -> None:
        """Turn CloudWatch alarm state changes (prefix-matched) into incidents."""
        ingest = self._function(
            "IngestFunction",
            image="jobs",
            handler="ingest_handler",
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={"INGEST_ALARM_PREFIX": alarm_prefix},
        )
        ingest.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:ListTagsForResource"],
                resources=[self._alarm_arn(alarm_prefix)],
            )
        )
        events.Rule(
            self,
            "AlarmIngestRule",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={
                    "state": {"value": ["ALARM"]},
                    "alarmName": [{"prefix": alarm_prefix}],
                },
            ),
            targets=[
                targets.LambdaFunction(ingest, retry_attempts=2, max_event_age=Duration.minutes(5))
            ],
        )

    def _demo_function(self) -> lambda_.DockerImageFunction:
        """The demo simulator: writes fake service logs/metrics and drives `if-*` alarms."""
        demo = self._function(
            "DemoFunction",
            image="jobs",
            handler="demo_handler",
            timeout=Duration.seconds(300),
            memory_size=512,
            environment={"DEMO_INTERVAL_SECONDS": "8"},
        )
        cfn_function = demo.node.default_child
        assert isinstance(cfn_function, lambda_.CfnFunction)
        cfn_function.reserved_concurrent_executions = 1
        lambda_.EventInvokeConfig(
            self,
            "DemoInvokeConfig",
            function=demo,
            retry_attempts=0,
            max_event_age=Duration.seconds(60),
        )
        demo_group = f"arn:aws:logs:{self.region}:{self.account}:log-group:/incidentflow/demo/*"
        demo.add_to_role_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:TagResource"],
                resources=[demo_group],
            )
        )
        demo.add_to_role_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[demo_group, f"{demo_group}:*"],
            )
        )
        demo.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "IncidentFlow/Demo"}},
            )
        )
        demo.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:SetAlarmState",
                    "cloudwatch:TagResource",
                    "cloudwatch:DescribeAlarms",
                ],
                resources=[self._alarm_arn(DEMO_ALARM_PREFIX)],
            )
        )
        return demo

    def _alarm_arn(self, prefix: str) -> str:
        return f"arn:aws:cloudwatch:{self.region}:{self.account}:alarm:{prefix}*"

    def _distribution(
        self, bucket: s3.Bucket, http_api: apigwv2.HttpApi
    ) -> cloudfront.Distribution:
        spa_rewrite = cloudfront.Function(
            self,
            "SpaRewrite",
            code=cloudfront.FunctionCode.from_inline(SPA_REWRITE_CODE),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            comment="Serve index.html for dashboard routes",
        )
        api_origin = origins.HttpOrigin(
            f"{http_api.api_id}.execute-api.{self.region}.{self.url_suffix}",
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )
        return cloudfront.Distribution(
            self,
            "Distribution",
            comment="IncidentFlow dashboard and API",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_rewrite,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=(
                        cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER
                    ),
                )
            },
        )

    def _sign_in(
        self, distribution: cloudfront.Distribution
    ) -> tuple[cognito.UserPool, cognito.UserPoolClient, cognito.UserPoolDomain]:
        user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            password_policy=cognito.PasswordPolicy(min_length=12),
            removal_policy=RemovalPolicy.DESTROY,
        )
        for group in ("viewer", "operator"):
            cognito.UserPoolGroup(
                self, f"{group.capitalize()}Group", user_pool=user_pool, group_name=group
            )
        domain = user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"incidentflow-{self.account}"
            ),
        )
        site_url = f"https://{distribution.distribution_domain_name}/"
        client = user_pool.add_client(
            "WebClient",
            generate_secret=False,
            prevent_user_existence_errors=True,
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[site_url],
                logout_urls=[site_url],
            ),
        )
        return user_pool, client, domain

    def _function(
        self,
        construct_id: str,
        *,
        image: str,
        timeout: Duration,
        memory_size: int,
        environment: dict[str, str],
        handler: str | None = None,
        function_name: str | None = None,
    ) -> lambda_.DockerImageFunction:
        tag = f"{image}-{self._image_tag}"
        if handler is None:
            code = lambda_.DockerImageCode.from_ecr(self._repository, tag_or_digest=tag)
            logging: dict[str, Any] = {}
        else:
            code = lambda_.DockerImageCode.from_ecr(
                self._repository,
                tag_or_digest=tag,
                entrypoint=_JOBS_ENTRYPOINT,
                cmd=[f"incidentflow.lambda_handlers.{handler}"],
            )
            logging = {
                "logging_format": lambda_.LoggingFormat.JSON,
                "application_log_level_v2": lambda_.ApplicationLogLevel.INFO,
                "system_log_level_v2": lambda_.SystemLogLevel.WARN,
            }
        log_group = logs.LogGroup(
            self,
            f"{construct_id}Logs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        function = lambda_.DockerImageFunction(
            self,
            construct_id,
            code=code,
            function_name=function_name,
            architecture=lambda_.Architecture.X86_64,
            timeout=timeout,
            memory_size=memory_size,
            log_group=log_group,
            environment={
                "HOME": "/tmp",
                "INCIDENTFLOW_SSM_PATH": SSM_PATH,
                "DATABASE_NULL_POOL": "true",
                **environment,
            },
            **logging,
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParametersByPath", "ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/incidentflow*"],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[f"arn:aws:kms:{self.region}:{self.account}:key/*"],
                conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}},
            )
        )
        return function

    def _budget(self, budget_email: str | None) -> None:
        notifications = None
        if budget_email:
            notifications = [
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=threshold,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=budget_email, subscription_type="EMAIL"
                        )
                    ],
                )
                for threshold in BUDGET_THRESHOLDS
            ]
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="incidentflow-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=BUDGET_USD, unit="USD"),
            ),
            notifications_with_subscribers=notifications,
        )
