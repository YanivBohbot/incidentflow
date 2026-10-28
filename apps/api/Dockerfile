# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install application dependencies before copying migration files to keep the
# dependency layer reusable across source-only changes.
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 incidentflow \
    && useradd --uid 10001 --gid incidentflow --create-home incidentflow

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=incidentflow:incidentflow alembic.ini ./
COPY --chown=incidentflow:incidentflow alembic ./alembic

USER incidentflow

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "incidentflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
