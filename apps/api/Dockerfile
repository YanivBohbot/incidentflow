# syntax=docker/dockerfile:1
# One image serves local Compose and four AWS Lambda functions: the api Lambda runs this CMD
# behind the Lambda Web Adapter; worker, sweeper, and migrate override the command with
# `python -m awslambdaric incidentflow.lambda_handlers.<name>`.

# The MongoDB MCP server (Node) runs as a stdio subprocess on Lambda. It is installed in a Node
# stage on the same Debian release as the Python base so any native modules match its glibc.
FROM node:22.23.3-trixie-slim AS mongodb-mcp

ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

RUN npm install --global --omit=dev mongodb-mcp-server@3.2.2 \
    && npm cache clean --force

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# The AWS Labs CloudWatch MCP server pins its own mcp, pydantic, and boto3 versions, so it gets
# an isolated virtual environment instead of the API's site-packages. Installing it at build time
# avoids a PyPI download inside each investigation's timeout.
RUN python -m venv /opt/cloudwatch-mcp \
    && /opt/cloudwatch-mcp/bin/pip install awslabs.cloudwatch-mcp-server==0.3.1

# Install application dependencies before copying migration files to keep the
# dependency layer reusable across source-only changes.
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.12-slim AS runtime

# Lambda's filesystem is read-only outside /tmp, so everything the MCP subprocesses write
# (home directory, npm cache, MongoDB MCP logs) goes there.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NPM_CONFIG_CACHE=/tmp/.npm \
    NPM_CONFIG_UPDATE_NOTIFIER=false

RUN groupadd --gid 10001 incidentflow \
    && useradd --uid 10001 --gid incidentflow --create-home incidentflow

# Lambda runs every executable in /opt/extensions; locally the adapter is never started.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

COPY --from=mongodb-mcp /usr/local/bin/node /usr/local/bin/node
COPY --from=mongodb-mcp /usr/local/lib/node_modules/mongodb-mcp-server \
    /usr/local/lib/node_modules/mongodb-mcp-server
RUN ln -s /usr/local/lib/node_modules/mongodb-mcp-server/dist/esm/index.js \
    /usr/local/bin/mongodb-mcp-server

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /opt/cloudwatch-mcp /opt/cloudwatch-mcp
COPY --chown=incidentflow:incidentflow alembic.ini ./
COPY --chown=incidentflow:incidentflow alembic ./alembic

USER incidentflow

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "incidentflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
