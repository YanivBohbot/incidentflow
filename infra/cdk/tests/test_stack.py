"""Synthesis assertions for the IncidentFlow AWS deployment (no AWS, no network, no CDK CLI)."""

import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from incidentflow_cdk.github_deploy_stack import GithubDeployStack
from incidentflow_cdk.names import (
    GITHUB_DEPLOY_SUBJECT,
    MIGRATE_FUNCTION_NAME,
    REPOSITORY_NAME,
    web_bucket_name,
)
from incidentflow_cdk.stack import SPA_REWRITE_CODE, IncidentFlowStack

ACCOUNT = "123456789012"
REGION = "us-east-1"
ENV = cdk.Environment(account=ACCOUNT, region=REGION)
CACHING_DISABLED_ID = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ALL_VIEWER_EXCEPT_HOST_HEADER_ID = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
JOB_FUNCTIONS = ("WorkerFunction", "SweeperFunction", "MigrateFunction")
ALL_FUNCTIONS = ("ApiFunction", *JOB_FUNCTIONS)


def _synth(budget_email: str | None = None) -> Template:
    app = cdk.App()
    stack = IncidentFlowStack(
        app, "IncidentFlow", image_tag="latest", budget_email=budget_email, env=ENV
    )
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template() -> Template:
    return _synth()


@pytest.fixture(scope="module")
def resources(template: Template) -> dict[str, dict[str, Any]]:
    return template.to_json()["Resources"]


@pytest.fixture(scope="module")
def deploy_template() -> Template:
    app = cdk.App()
    return Template.from_stack(GithubDeployStack(app, "IncidentFlowGithubDeploy", env=ENV))


def _of_type(resources: dict[str, dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {name: r for name, r in resources.items() if r["Type"] == kind}


def _function(resources: dict[str, dict[str, Any]], prefix: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (name, r)
        for name, r in _of_type(resources, "AWS::Lambda::Function").items()
        if name.startswith(prefix)
    ]
    assert len(matches) == 1, f"expected one function named {prefix}*, got {matches}"
    return matches[0]


def _env(resources: dict[str, dict[str, Any]], prefix: str) -> dict[str, Any]:
    return _function(resources, prefix)[1]["Properties"]["Environment"]["Variables"]


def _role_statements(resources: dict[str, dict[str, Any]], role_name: str) -> list[dict]:
    statements: list[dict] = []
    for policy in _of_type(resources, "AWS::IAM::Policy").values():
        roles = policy["Properties"]["Roles"]
        if {"Ref": role_name} in roles:
            statements.extend(policy["Properties"]["PolicyDocument"]["Statement"])
    return statements


def _function_statements(resources: dict[str, dict[str, Any]], prefix: str) -> list[dict]:
    role = _function(resources, prefix)[1]["Properties"]["Role"]["Fn::GetAtt"][0]
    return _role_statements(resources, role)


def _actions(statement: dict) -> set[str]:
    actions = statement["Action"]
    return {actions} if isinstance(actions, str) else set(actions)


# --- Dependency graph ------------------------------------------------------------------------


def _references(value: Any) -> Iterator[str]:
    """Yield every logical id referenced by Ref, Fn::GetAtt and Fn::Sub inside ``value``."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "Ref" and isinstance(inner, str):
                yield inner
            elif key == "Fn::GetAtt":
                target = inner[0] if isinstance(inner, list) else inner.split(".")[0]
                yield target
            elif key == "Fn::Sub":
                text = inner[0] if isinstance(inner, list) else inner
                for match in re.findall(r"\$\{([^}!][^}]*)\}", text):
                    yield match.split(".")[0]
                if isinstance(inner, list) and len(inner) > 1:
                    yield from _references(inner[1])
            else:
                yield from _references(inner)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _dependency_graph(resources: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for name, resource in resources.items():
        edges = {ref for ref in _references(resource) if ref in resources}
        depends_on = resource.get("DependsOn", [])
        edges |= {depends_on} if isinstance(depends_on, str) else set(depends_on)
        graph[name] = edges
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: list[str] = []
    done: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            return visiting[visiting.index(node) :] + [node]
        if node in done:
            return None
        visiting.append(node)
        for target in sorted(graph.get(node, ())):
            cycle = visit(target)
            if cycle:
                return cycle
        visiting.pop()
        done.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def test_cycle_detector_reports_a_hand_built_cycle() -> None:
    resources = {
        "Client": {"Type": "X", "Properties": {"Url": {"Fn::GetAtt": "Cdn.DomainName"}}},
        "Cdn": {"Type": "X", "Properties": {"Origin": {"Fn::Sub": "${Api}.example"}}},
        "Api": {"Type": "X", "DependsOn": "Auth"},
        "Auth": {"Type": "X", "Properties": {"Audience": [{"Ref": "Client"}]}},
        "Other": {"Type": "X", "Properties": {"Region": {"Ref": "AWS::Region"}}},
    }

    graph = _dependency_graph(resources)

    assert graph["Other"] == set()
    assert _find_cycle(graph) == ["Api", "Auth", "Client", "Cdn", "Api"]


def test_template_has_no_dependency_cycle(resources: dict[str, dict[str, Any]]) -> None:
    graph = _dependency_graph(resources)

    assert sum(len(edges) for edges in graph.values()) > 20
    assert _find_cycle(graph) is None


def test_client_callback_and_logout_point_at_distribution(
    resources: dict[str, dict[str, Any]],
) -> None:
    (distribution,) = _of_type(resources, "AWS::CloudFront::Distribution")
    expected = [{"Fn::Join": ["", ["https://", {"Fn::GetAtt": [distribution, "DomainName"]}, "/"]]}]
    (client,) = _of_type(resources, "AWS::Cognito::UserPoolClient").values()

    assert client["Properties"]["CallbackURLs"] == expected
    assert client["Properties"]["LogoutURLs"] == expected


# --- Cost and leak guardrails ----------------------------------------------------------------


def test_no_vpc_or_nat(resources: dict[str, dict[str, Any]]) -> None:
    kinds = {r["Type"] for r in resources.values()}

    assert not {k for k in kinds if k.startswith("AWS::EC2::")}
    for _, function in _of_type(resources, "AWS::Lambda::Function").items():
        assert "VpcConfig" not in function["Properties"]


def test_every_log_group_has_14_day_retention(resources: dict[str, dict[str, Any]]) -> None:
    log_groups = _of_type(resources, "AWS::Logs::LogGroup")
    functions = _of_type(resources, "AWS::Lambda::Function")

    assert len(log_groups) == len(functions) == 4
    assert all(g["Properties"]["RetentionInDays"] == 14 for g in log_groups.values())
    for function in functions.values():
        log_group = function["Properties"]["LoggingConfig"]["LogGroup"]["Ref"]
        assert log_group in log_groups
    # Custom resources bring their own Lambda with a never-expiring log group.
    assert not [r for r in resources.values() if r["Type"].startswith("Custom::")]


def test_budget_is_10_usd_monthly(template: Template) -> None:
    (budget,) = template.find_resources("AWS::Budgets::Budget").values()
    properties = budget["Properties"]

    assert properties["Budget"]["BudgetLimit"] == {"Amount": 10, "Unit": "USD"}
    assert properties["Budget"]["TimeUnit"] == "MONTHLY"
    assert properties["Budget"]["BudgetType"] == "COST"
    assert "NotificationsWithSubscribers" not in properties


def test_budget_notifies_the_configured_subscriber_at_50_80_100_percent() -> None:
    subscriber = "budget-subscriber-from-context"
    (budget,) = _synth(subscriber).find_resources("AWS::Budgets::Budget").values()

    notifications = budget["Properties"]["NotificationsWithSubscribers"]
    assert [n["Notification"]["Threshold"] for n in notifications] == [50, 80, 100]
    for notification in notifications:
        assert notification["Subscribers"] == [{"SubscriptionType": "EMAIL", "Address": subscriber}]


_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD")
# A setting name such as "dynamodb", a path, or a URL without credentials.
_NAME_VALUE = re.compile(r"^[A-Za-z0-9_.:/-]{0,128}$")
_CREDENTIAL_SHAPE = re.compile(r"sk-|ghp_|github_pat_|pcsk_|AKIA|://[^/@\s]+:[^/@\s]+@")


def test_no_lambda_environment_value_looks_secret(resources: dict[str, dict[str, Any]]) -> None:
    for prefix in ALL_FUNCTIONS:
        for key, value in _env(resources, prefix).items():
            assert key not in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
            assert key != "MCP_OAUTH_STORAGE_ENCRYPTION_KEY"
            text = json.dumps(value)
            assert not _CREDENTIAL_SHAPE.search(text), (prefix, key)
            if _SECRET_NAME.search(key):
                # Only a literal name (or a reference to a resource) may sit behind such a key.
                assert isinstance(value, dict) or _NAME_VALUE.match(value), (prefix, key)


def test_every_function_shares_runtime_environment(resources: dict[str, dict[str, Any]]) -> None:
    for prefix in ALL_FUNCTIONS:
        env = _env(resources, prefix)
        assert env["HOME"] == "/tmp"
        assert env["INCIDENTFLOW_SSM_PATH"] == "/incidentflow/"
        assert env["DATABASE_NULL_POOL"] == "true"


def test_job_queue_url_set_wherever_jobs_are_sent(resources: dict[str, dict[str, Any]]) -> None:
    (queue,) = [
        name
        for name, r in _of_type(resources, "AWS::SQS::Queue").items()
        if "RedrivePolicy" in r["Properties"]
    ]
    for prefix in ("ApiFunction", "WorkerFunction", "SweeperFunction"):
        assert _env(resources, prefix)["JOB_QUEUE_URL"] == {"Ref": queue}


def test_every_function_reads_only_incidentflow_parameters(
    resources: dict[str, dict[str, Any]],
) -> None:
    parameter_arn = f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/incidentflow*"
    for prefix in ALL_FUNCTIONS:
        statements = _function_statements(resources, prefix)
        ssm = [s for s in statements if any(a.startswith("ssm:") for a in _actions(s))]
        kms = [s for s in statements if any(a.startswith("kms:") for a in _actions(s))]

        assert [_actions(s) for s in ssm] == [{"ssm:GetParametersByPath", "ssm:GetParameter"}]
        assert ssm[0]["Resource"] == parameter_arn
        assert [_actions(s) for s in kms] == [{"kms:Decrypt"}]
        assert kms[0]["Resource"] == f"arn:aws:kms:{REGION}:{ACCOUNT}:key/*"
        assert kms[0]["Condition"] == {
            "StringEquals": {"kms:ViaService": f"ssm.{REGION}.amazonaws.com"}
        }


# --- Functions -------------------------------------------------------------------------------


def test_functions_are_x86_64(resources: dict[str, dict[str, Any]]) -> None:
    functions = _of_type(resources, "AWS::Lambda::Function")

    assert len(functions) == 4
    assert all(f["Properties"]["Architectures"] == ["x86_64"] for f in functions.values())
    assert all(f["Properties"]["PackageType"] == "Image" for f in functions.values())


def test_no_function_url_or_reserved_concurrency(resources: dict[str, dict[str, Any]]) -> None:
    assert not _of_type(resources, "AWS::Lambda::Url")
    for function in _of_type(resources, "AWS::Lambda::Function").values():
        assert "ReservedConcurrentExecutions" not in function["Properties"]


def test_function_timeouts(resources: dict[str, dict[str, Any]]) -> None:
    timeouts = {
        prefix: _function(resources, prefix)[1]["Properties"]["Timeout"] for prefix in ALL_FUNCTIONS
    }

    assert timeouts["ApiFunction"] == 30
    assert timeouts["WorkerFunction"] == 900
    assert timeouts["MigrateFunction"] == 300


def _image_uri(tag: str) -> dict[str, Any]:
    return {
        "Fn::Join": [
            "",
            [
                f"{ACCOUNT}.dkr.ecr.{REGION}.",
                {"Ref": "AWS::URLSuffix"},
                f"/{REPOSITORY_NAME}:{tag}",
            ],
        ]
    }


def test_functions_run_the_api_and_jobs_image_tags(resources: dict[str, dict[str, Any]]) -> None:
    api = _function(resources, "ApiFunction")[1]["Properties"]

    assert api["Code"] == {"ImageUri": _image_uri("api-latest")}
    assert "ImageConfig" not in api
    for prefix, handler in (
        ("WorkerFunction", "worker_handler"),
        ("SweeperFunction", "sweeper_handler"),
        ("MigrateFunction", "migrate_handler"),
    ):
        properties = _function(resources, prefix)[1]["Properties"]
        assert properties["Code"] == {"ImageUri": _image_uri("jobs-latest")}
        assert properties["ImageConfig"] == {
            "EntryPoint": ["python", "-m", "awslambdaric"],
            "Command": [f"incidentflow.lambda_handlers.{handler}"],
        }


def test_job_functions_log_json_at_info(resources: dict[str, dict[str, Any]]) -> None:
    for prefix in JOB_FUNCTIONS:
        logging_config = _function(resources, prefix)[1]["Properties"]["LoggingConfig"]
        assert logging_config["LogFormat"] == "JSON"
        assert logging_config["ApplicationLogLevel"] == "INFO"


def test_api_function_verifies_cognito_tokens(resources: dict[str, dict[str, Any]]) -> None:
    (pool,) = _of_type(resources, "AWS::Cognito::UserPool")
    (client,) = _of_type(resources, "AWS::Cognito::UserPoolClient")
    env = _env(resources, "ApiFunction")

    assert env["AUTH_ENABLED"] == "true"
    assert env["OIDC_ISSUER_URL"] == {
        "Fn::Join": ["", [f"https://cognito-idp.{REGION}.amazonaws.com/", {"Ref": pool}]]
    }
    assert env["OIDC_CLIENT_ID"] == {"Ref": client}
    assert env["AWS_LWA_PORT"] == "8000"
    assert env["AWS_LWA_READINESS_CHECK_PATH"] == "/health"


def test_worker_environment(resources: dict[str, dict[str, Any]]) -> None:
    (table,) = _of_type(resources, "AWS::DynamoDB::Table")
    env = _env(resources, "WorkerFunction")

    assert env["JOB_TIMEOUT_SECONDS"] == "780"
    assert env["MCP_OAUTH_TOKEN_STORE"] == "dynamodb"
    assert env["MCP_OAUTH_DYNAMODB_TABLE"] == {"Ref": table}
    assert env["MONGODB_MCP_TRANSPORT"] == "stdio"
    assert env["MDB_MCP_TELEMETRY"] == "disabled"
    assert "MONGODB_MCP_COMMAND_ARGS" not in env
    assert env["GITHUB_MCP_TRANSPORT"] == "http"
    assert env["GITHUB_MCP_URL"] == "https://api.githubcopilot.com/mcp/"
    assert env["CLOUDWATCH_MCP_COMMAND"] == (
        "/opt/cloudwatch-mcp/bin/awslabs.cloudwatch-mcp-server"
    )
    assert env["CLOUDWATCH_MCP_COMMAND_ARGS"] == ""
    for flag in (
        "JIRA_MCP_ENABLED",
        "JIRA_MCP_WRITE_ENABLED",
        "MONGODB_MCP_ENABLED",
        "PINECONE_ENABLED",
        "GITHUB_MCP_ENABLED",
        "CLOUDWATCH_MCP_ENABLED",
    ):
        assert env[flag] == "true", flag


def test_token_table_matches_dynamodb_store_schema(template: Template) -> None:
    (table,) = template.find_resources("AWS::DynamoDB::Table").values()
    properties = table["Properties"]

    assert properties["KeySchema"] == [
        {"AttributeName": "collection", "KeyType": "HASH"},
        {"AttributeName": "key", "KeyType": "RANGE"},
    ]
    assert sorted(properties["AttributeDefinitions"], key=lambda a: a["AttributeName"]) == [
        {"AttributeName": "collection", "AttributeType": "S"},
        {"AttributeName": "key", "AttributeType": "S"},
    ]
    assert properties["BillingMode"] == "PAY_PER_REQUEST"
    assert properties["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}


def test_only_the_worker_reaches_the_token_table(resources: dict[str, dict[str, Any]]) -> None:
    (table,) = _of_type(resources, "AWS::DynamoDB::Table")
    statements = [
        s
        for s in _function_statements(resources, "WorkerFunction")
        if any(a.startswith("dynamodb:") for a in _actions(s))
    ]

    assert len(statements) == 1
    assert _actions(statements[0]) == {
        "dynamodb:DescribeTable",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:UpdateTimeToLive",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
    }
    assert statements[0]["Resource"] == {"Fn::GetAtt": [table, "Arn"]}
    for prefix in ("ApiFunction", "SweeperFunction", "MigrateFunction"):
        for statement in _function_statements(resources, prefix):
            assert not any(a.startswith("dynamodb:") for a in _actions(statement))


def test_worker_cloudwatch_access_is_read_only(resources: dict[str, dict[str, Any]]) -> None:
    actions = set()
    for statement in _function_statements(resources, "WorkerFunction"):
        actions |= {a for a in _actions(statement) if a.split(":")[0] in {"cloudwatch", "logs"}}

    assert actions == {
        "cloudwatch:DescribeAlarms",
        "cloudwatch:GetMetricData",
        "logs:StartQuery",
        "logs:GetQueryResults",
        "logs:StopQuery",
    }


def test_api_and_sweeper_may_send_jobs(resources: dict[str, dict[str, Any]]) -> None:
    for prefix in ("ApiFunction", "SweeperFunction"):
        actions = set().union(*(_actions(s) for s in _function_statements(resources, prefix)))
        assert "sqs:SendMessage" in actions
        assert "sqs:ReceiveMessage" not in actions
    migrate = _function_statements(resources, "MigrateFunction")
    assert not any(a.startswith("sqs:") for s in migrate for a in _actions(s))


# --- Queue and schedule ----------------------------------------------------------------------


def test_queue_visibility_at_least_worker_timeout(resources: dict[str, dict[str, Any]]) -> None:
    worker_timeout = _function(resources, "WorkerFunction")[1]["Properties"]["Timeout"]
    for queue in _of_type(resources, "AWS::SQS::Queue").values():
        if "RedrivePolicy" in queue["Properties"]:
            assert queue["Properties"]["VisibilityTimeout"] >= worker_timeout


def test_dlq_after_3_receives(resources: dict[str, dict[str, Any]]) -> None:
    queues = _of_type(resources, "AWS::SQS::Queue")
    (jobs,) = [q for q in queues.values() if "RedrivePolicy" in q["Properties"]]
    redrive = jobs["Properties"]["RedrivePolicy"]

    assert redrive["maxReceiveCount"] == 3
    dlq = redrive["deadLetterTargetArn"]["Fn::GetAtt"][0]
    assert dlq in queues


def test_worker_max_concurrency_2_batch_1(resources: dict[str, dict[str, Any]]) -> None:
    (worker, _) = _function(resources, "WorkerFunction")
    (mapping,) = _of_type(resources, "AWS::Lambda::EventSourceMapping").values()
    properties = mapping["Properties"]

    assert properties["FunctionName"] == {"Ref": worker}
    assert properties["BatchSize"] == 1
    assert properties["ScalingConfig"] == {"MaximumConcurrency": 2}
    assert properties["FunctionResponseTypes"] == ["ReportBatchItemFailures"]


def test_sweeper_every_15_minutes(resources: dict[str, dict[str, Any]]) -> None:
    (sweeper, _) = _function(resources, "SweeperFunction")
    (rule,) = _of_type(resources, "AWS::Events::Rule").values()

    assert rule["Properties"]["ScheduleExpression"] == "rate(15 minutes)"
    assert rule["Properties"]["Targets"][0]["Arn"] == {"Fn::GetAtt": [sweeper, "Arn"]}


# --- API, sign-in, web -----------------------------------------------------------------------


def test_api_routes_use_jwt_authorizer(resources: dict[str, dict[str, Any]]) -> None:
    (pool,) = _of_type(resources, "AWS::Cognito::UserPool")
    (client,) = _of_type(resources, "AWS::Cognito::UserPoolClient")
    routes = _of_type(resources, "AWS::ApiGatewayV2::Route").values()
    (authorizer_id, authorizer) = next(
        iter(_of_type(resources, "AWS::ApiGatewayV2::Authorizer").items())
    )

    assert [r["Properties"]["RouteKey"] for r in routes] == ["ANY /api/{proxy+}"]
    (route,) = routes
    assert route["Properties"]["AuthorizationType"] == "JWT"
    assert route["Properties"]["AuthorizerId"] == {"Ref": authorizer_id}
    assert authorizer["Properties"]["AuthorizerType"] == "JWT"
    assert authorizer["Properties"]["JwtConfiguration"] == {
        "Audience": [{"Ref": client}],
        "Issuer": {
            "Fn::Join": ["", [f"https://cognito-idp.{REGION}.amazonaws.com/", {"Ref": pool}]]
        },
    }


def test_self_signup_disabled(template: Template) -> None:
    (pool,) = template.find_resources("AWS::Cognito::UserPool").values()
    properties = pool["Properties"]

    assert properties["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert properties["MfaConfiguration"] == "OPTIONAL"
    assert properties["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]
    groups = template.find_resources("AWS::Cognito::UserPoolGroup").values()
    assert sorted(g["Properties"]["GroupName"] for g in groups) == ["operator", "viewer"]
    (domain,) = template.find_resources("AWS::Cognito::UserPoolDomain").values()
    assert domain["Properties"]["Domain"] == f"incidentflow-{ACCOUNT}"


def test_app_client_uses_code_flow_without_secret(template: Template) -> None:
    (client,) = template.find_resources("AWS::Cognito::UserPoolClient").values()
    properties = client["Properties"]

    assert properties["GenerateSecret"] is False
    assert properties["AllowedOAuthFlows"] == ["code"]
    assert properties["AllowedOAuthFlowsUserPoolClient"] is True
    assert "openid" in properties["AllowedOAuthScopes"]
    assert properties["SupportedIdentityProviders"] == ["COGNITO"]


def test_distribution_routes_api_without_cache_and_spa_through_rewrite(
    resources: dict[str, dict[str, Any]],
) -> None:
    (config,) = [
        r["Properties"]["DistributionConfig"]
        for r in _of_type(resources, "AWS::CloudFront::Distribution").values()
    ]
    (spa_function,) = _of_type(resources, "AWS::CloudFront::Function")
    default = config["DefaultCacheBehavior"]
    (api,) = config["CacheBehaviors"]

    assert "CustomErrorResponses" not in config
    assert default["FunctionAssociations"] == [
        {
            "EventType": "viewer-request",
            "FunctionARN": {"Fn::GetAtt": [spa_function, "FunctionARN"]},
        }
    ]
    assert api["PathPattern"] == "/api/*"
    assert "FunctionAssociations" not in api
    assert api["CachePolicyId"] == CACHING_DISABLED_ID
    assert api["OriginRequestPolicyId"] == ALL_VIEWER_EXCEPT_HOST_HEADER_ID
    assert set(api["AllowedMethods"]) == {
        "GET",
        "HEAD",
        "OPTIONS",
        "PUT",
        "PATCH",
        "POST",
        "DELETE",
    }
    origins = {o["Id"]: o for o in config["Origins"]}
    api_origin = origins[api["TargetOriginId"]]
    assert api_origin["CustomOriginConfig"]["OriginProtocolPolicy"] == "https-only"
    (http_api,) = _of_type(resources, "AWS::ApiGatewayV2::Api")
    assert {"Ref": http_api} in api_origin["DomainName"]["Fn::Join"][1]
    s3_origin = origins[default["TargetOriginId"]]
    assert "OriginAccessControlId" in s3_origin


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the CloudFront Function")
@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("/", "/index.html"),
        ("/investigations/42", "/index.html"),
        ("/assets/index-abc.js", "/assets/index-abc.js"),
        ("/favicon.svg", "/favicon.svg"),
    ],
)
def test_spa_rewrite_sends_extensionless_paths_to_index(uri: str, expected: str) -> None:
    script = (
        SPA_REWRITE_CODE
        + f"\nprocess.stdout.write(handler({{request: {{uri: {json.dumps(uri)}}}}}).uri);"
    )

    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True, timeout=30
    )

    assert result.stdout == expected


def test_web_bucket_is_private(template: Template) -> None:
    (bucket,) = template.find_resources("AWS::S3::Bucket").values()
    properties = bucket["Properties"]

    assert properties["BucketName"] == web_bucket_name(ACCOUNT)
    assert properties["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert template.find_resources("AWS::CloudFront::OriginAccessControl")


def test_stack_outputs(template: Template, resources: dict[str, dict[str, Any]]) -> None:
    outputs = template.to_json()["Outputs"]
    (migrate, _) = _function(resources, "MigrateFunction")

    assert {
        "DistributionDomain",
        "DistributionId",
        "WebBucket",
        "UserPoolId",
        "UserPoolClientId",
        "CognitoDomain",
        "MigrateFunctionName",
    } <= set(outputs)
    assert outputs["MigrateFunctionName"]["Value"] == {"Ref": migrate}
    assert resources[migrate]["Properties"]["FunctionName"] == MIGRATE_FUNCTION_NAME


# --- GitHub deploy stack ---------------------------------------------------------------------


def test_deploy_role_trusts_only_master_of_repo(deploy_template: Template) -> None:
    roles = deploy_template.find_resources("AWS::IAM::Role")
    (role,) = roles.values()
    (statement,) = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    (provider,) = deploy_template.find_resources("AWS::IAM::OIDCProvider")

    assert role["Properties"]["RoleName"] == "incidentflow-github-deploy"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Principal"] == {"Federated": {"Ref": provider}}
    assert statement["Condition"] == {
        "StringEquals": {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": GITHUB_DEPLOY_SUBJECT,
        }
    }
    assert GITHUB_DEPLOY_SUBJECT == "repo:YanivBohbot/incidentflow:ref:refs/heads/master"


def test_github_oidc_provider_is_native(deploy_template: Template) -> None:
    (provider,) = deploy_template.find_resources("AWS::IAM::OIDCProvider").values()

    assert provider["Properties"]["Url"] == "https://token.actions.githubusercontent.com"
    assert provider["Properties"]["ClientIdList"] == ["sts.amazonaws.com"]
    assert not [
        r
        for r in deploy_template.to_json()["Resources"].values()
        if r["Type"].startswith("Custom::") or r["Type"] == "AWS::Lambda::Function"
    ]


def test_repository_keeps_last_10_images_and_lets_lambda_pull(
    deploy_template: Template,
) -> None:
    (repository,) = deploy_template.find_resources("AWS::ECR::Repository").values()
    properties = repository["Properties"]
    rules = json.loads(properties["LifecyclePolicy"]["LifecyclePolicyText"])["rules"]
    (pull,) = properties["RepositoryPolicyText"]["Statement"]

    assert properties["RepositoryName"] == REPOSITORY_NAME
    assert [r["selection"]["countNumber"] for r in rules] == [10]
    assert rules[0]["selection"]["countType"] == "imageCountMoreThan"
    assert pull["Principal"] == {"Service": "lambda.amazonaws.com"}
    assert set(pull["Action"]) == {"ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"}


def test_deploy_role_permissions_are_scoped(deploy_template: Template) -> None:
    resources = deploy_template.to_json()["Resources"]
    (role,) = _of_type(resources, "AWS::IAM::Role")
    statements = _role_statements(resources, role)
    by_action = {action: s for s in statements for action in _actions(s)}

    assert by_action["sts:AssumeRole"]["Resource"] == (
        f"arn:aws:iam::{ACCOUNT}:role/cdk-hnb659fds-*-role-{ACCOUNT}-{REGION}"
    )
    assert by_action["lambda:InvokeFunction"]["Resource"] == (
        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{MIGRATE_FUNCTION_NAME}"
    )
    bucket = web_bucket_name(ACCOUNT)
    assert by_action["s3:ListBucket"]["Resource"] == f"arn:aws:s3:::{bucket}"
    assert by_action["s3:PutObject"]["Resource"] == f"arn:aws:s3:::{bucket}/*"
    assert by_action["s3:DeleteObject"]["Resource"] == f"arn:aws:s3:::{bucket}/*"
    assert by_action["cloudfront:CreateInvalidation"]["Resource"] == (
        f"arn:aws:cloudfront::{ACCOUNT}:distribution/*"
    )
    assert by_action["ecr:GetAuthorizationToken"]["Resource"] == "*"
    assert "ecr:PutImage" in by_action
    assert all(s["Resource"] != "*" for a, s in by_action.items() if a.startswith("ecr:Put"))
    assert not [a for a in by_action if a.startswith(("iam:", "cloudformation:"))]


def test_deploy_stack_outputs(deploy_template: Template) -> None:
    assert {"DeployRoleArn", "RepositoryUri"} <= set(deploy_template.to_json()["Outputs"])
