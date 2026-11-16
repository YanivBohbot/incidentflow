"""Fixed physical names shared by both stacks.

The deploy role is created before the main stack exists, so it scopes its permissions by these
names instead of by cross-stack references (which would lock the stacks together with exports).
"""

REGION = "us-east-1"
REPOSITORY_NAME = "incidentflow-api"
MIGRATE_FUNCTION_NAME = "incidentflow-migrate"
DEPLOY_ROLE_NAME = "incidentflow-github-deploy"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_DEPLOY_SUBJECT = "repo:YanivBohbot/incidentflow:ref:refs/heads/master"
SSM_PATH = "/incidentflow/"


def web_bucket_name(account: str) -> str:
    """S3 names are global, so the account id keeps the dashboard bucket's name unique."""
    return f"incidentflow-web-{account}"
