"""CDK entry point. Deploy order:

1. `cdk deploy IncidentFlowGithubDeploy` (repository, GitHub OIDC provider, deploy role);
2. build and push `incidentflow-api:api-<sha>` and `incidentflow-api:jobs-<sha>`;
3. `cdk deploy IncidentFlow -c imageTag=<sha> [-c budgetEmail=<address>]`.

Context from `cdk.json`: the integration names and `ingestAlarmPrefix` (CloudWatch alarms whose
name starts with it become incidents; `if-`).
"""

import os

import aws_cdk as cdk

from incidentflow_cdk.github_deploy_stack import GithubDeployStack
from incidentflow_cdk.names import REGION
from incidentflow_cdk.stack import IncidentFlowStack, IntegrationSettings

app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)


def _context(key: str) -> str:
    value = app.node.try_get_context(key)
    if not value:
        raise SystemExit(
            f"Missing CDK context '{key}': pass -c {key}=<value> or set it in cdk.json."
        )
    return str(value)


GithubDeployStack(app, "IncidentFlowGithubDeploy", env=env)
IncidentFlowStack(
    app,
    "IncidentFlow",
    image_tag=_context("imageTag"),
    budget_email=app.node.try_get_context("budgetEmail") or None,
    integration_settings=IntegrationSettings(
        github_repositories=_context("githubRepositories"),
        cloudwatch_log_groups=_context("cloudwatchLogGroups"),
        pinecone_index_name=_context("pineconeIndexName"),
        pinecone_namespace=_context("pineconeNamespace"),
        mongodb_database=_context("mongodbDatabase"),
        mongodb_events_collection=_context("mongodbEventsCollection"),
    ),
    ingest_alarm_prefix=_context("ingestAlarmPrefix"),
    env=env,
)

app.synth()
