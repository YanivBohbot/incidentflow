"""CDK entry point: `cdk deploy -c imageTag=<sha> [-c budgetEmail=<address>] --all`."""

import os

import aws_cdk as cdk

from incidentflow_cdk.github_deploy_stack import GithubDeployStack
from incidentflow_cdk.names import REGION
from incidentflow_cdk.stack import IncidentFlowStack

app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)

GithubDeployStack(app, "IncidentFlowGithubDeploy", env=env)
IncidentFlowStack(
    app,
    "IncidentFlow",
    image_tag=app.node.try_get_context("imageTag") or "latest",
    # Supplied at deploy time (e.g. from a GitHub secret); never committed.
    budget_email=app.node.try_get_context("budgetEmail") or None,
    env=env,
)

app.synth()
