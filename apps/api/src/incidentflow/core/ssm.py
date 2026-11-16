"""Load secrets from AWS SSM Parameter Store into the process environment."""

import os
from typing import Any


def load_ssm_parameters_into_environ(path: str, *, client: Any | None = None) -> list[str]:
    """Copy parameters under ``path`` into ``os.environ`` and return the names it set.

    ``/incidentflow/OPENAI_API_KEY`` becomes ``OPENAI_API_KEY``. A variable that is already set
    wins. Only names are returned; values are never logged.
    """
    if client is None:
        import boto3

        client = boto3.client("ssm")
    prefix = path.rstrip("/") + "/"
    loaded: list[str] = []
    request: dict[str, Any] = {"Path": path, "Recursive": False, "WithDecryption": True}
    while True:
        response = client.get_parameters_by_path(**request)
        for parameter in response.get("Parameters", []):
            name = parameter["Name"].removeprefix(prefix)
            if name and name not in os.environ:
                os.environ[name] = parameter["Value"]
                loaded.append(name)
        token = response.get("NextToken")
        if not token:
            return loaded
        request["NextToken"] = token
