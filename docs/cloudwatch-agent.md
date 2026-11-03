# CloudWatch Observability Agent

The CloudWatch Observability Agent is IncidentFlow's fifth specialist. It queries AWS CloudWatch
**read-only** for the active alarms, metrics, and logs related to an incident. It then returns a
structured finding with evidence-backed root-cause hypotheses.

## Role and supervisor integration

```
POST /api/investigations
  → LangGraph workflow (validate → prepare → investigate → …)
    → Supervisor (create_agent + LLMToolSelectorMiddleware)
      → ask_cloudwatch(incident_context, service_name?, incident_id?)   ← a tool
        → CloudWatchMCPClient (stdio) → awslabs.cloudwatch-mcp-server → AWS CloudWatch
        → CloudWatch Observability Agent (create_agent)                 ← a subagent
            chooses get_active_alarms / get_metric_data / execute_log_insights_query
            → CloudWatchFinding (ToolStrategy)
        → application guardrails → CloudWatchFinding (JSON)
      → other specialists, only when needed
    → InvestigationReport (final synthesis)
```

- The agent follows the **Supervisor + Subagents as Tools** pattern: `ask_cloudwatch` is a
  LangChain tool that runs a real `create_agent` subagent, like every other specialist.
- The supervisor selects it for production symptoms: HTTP 5xx errors, latency, and alarms. Call
  limits (two per specialist) and network-error retries apply as for the other delegations.
- The **subagent chooses its reads** among exactly three of the server's tools:

  | MCP tool | What it reads | Why |
  |---|---|---|
  | `get_active_alarms` | Alarms currently in ALARM | Which production signal is firing |
  | `get_metric_data` | The metric a relevant alarm watches (max. 3 reads) | When the problem started and how large it is |
  | `execute_log_insights_query` | Error, exception, timeout, and 5xx lines in the allowlisted log groups | What the application says about the cause |

  The delegation message gives the time window (always the last
  `CLOUDWATCH_MCP_LOOKBACK_MINUTES` minutes) and the exact read parameters.
- Safety lives in the subagent's **middleware** (`agent/agents_specialist/cloudwatch.py`):
  `CloudWatchReadOnlyPolicyMiddleware` checks every model-chosen call before it reaches AWS,
  converts timestamps to UTC, and replaces raw AWS errors with a category;
  `ToolCallLimitMiddleware` (5 reads) and `ModelCallLimitMiddleware` (5 turns) bound the loop.
- `agent/tools/cloudwatch_tools.py` opens the MCP session, runs the agent, then applies
  `collect_reads` and `keep_cited_hypotheses`.

## `CloudWatchFinding` contract

The contract is defined in `agent/findings/`. Its fields are
`incident_id`, `service_name`, `investigation_status` (`completed` | `partial` | `unavailable`),
`time_window`, `summary`, `observations`, `relevant_metrics`, `relevant_log_events`,
`active_alarms`, `root_cause_hypotheses`, `confidence`, `recommended_actions`,
`evidence_references`, and `errors`.

Deterministic guardrails are applied after the agent run:

- Each successful read gets a reference, derived by code from the agent's tool calls:
  `alarms:active`, `metric:<namespace>/<metric>`, or `logs:<log groups>`.
- A hypothesis must cite at least one reference, and every reference it cites must have been
  read. Other hypotheses are removed, and the removal is reported in `observations`.
- `investigation_status`, `time_window`, `evidence_references`, and `errors` are set by code,
  never by the model.
- When the reads return nothing (no alarm, no metric datapoint, no log event), the agent's
  finding is discarded: the result contains no hypothesis, and its confidence is 0.
- `confidence` is a subjective estimate, not a calibrated probability.
- The server reports timestamps in the host time zone. They are converted to UTC before the
  model reads them.

## MCP server

| Item | Verified value |
|---|---|
| Package | `awslabs.cloudwatch-mcp-server` (pinned to `0.3.1`) |
| Transport | stdio |
| Launch (Windows) | `uv tool run --from awslabs.cloudwatch-mcp-server@0.3.1 awslabs.cloudwatch-mcp-server.exe` |
| Launch (Linux/macOS) | same command, without `.exe` |
| Exposed tools | 19 (alarms, metrics, PromQL, logs, recommendations) |
| Allowed tools | `get_active_alarms`, `get_metric_data`, `execute_log_insights_query` |

The connection uses `langchain[mcp]` (`MCPAdapter`) and `fastmcp`, which the project already
depends on. **No Python dependency was added.** `uv` must be installed on the machine that runs
the API.

The client (`agent/mcp_clients/cloudwatch.py`) adds three protections:

1. **Closed tool allowlist.** Only the three tools above are kept; the other 16 (PromQL,
   recommendations, alarm history, `cancel_logs_insight_query`, and so on) are never used.
   Start-up fails cleanly if a required tool is missing.
2. **Argument checks before every MCP call.** The client rejects:
   - `profile_name` and `region`, which the server accepts on every tool and which would allow
     switching to an administrator profile;
   - log groups outside `CLOUDWATCH_MCP_LOG_GROUPS`;
   - `log_group_identifiers`.
3. **Filtered environment.** The subprocess receives only `PATH`, system variables, and `AWS_*`
   and `UV_*` variables. `OPENAI_API_KEY`, `DATABASE_URL`, and other secrets never reach it.

## Configuration (`apps/api/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDWATCH_MCP_ENABLED` | `false` | Enables the agent |
| `CLOUDWATCH_MCP_AWS_PROFILE` | empty | Local AWS profile; leave empty on AWS (IAM role) |
| `CLOUDWATCH_MCP_AWS_REGION` | `us-east-1` | Region to query |
| `CLOUDWATCH_MCP_LOG_GROUPS` | empty | Allowed log groups, comma-separated |
| `CLOUDWATCH_MCP_TIMEOUT_SECONDS` | `90` | Total budget for server start-up and all reads |
| `CLOUDWATCH_MCP_LOOKBACK_MINUTES` | `60` | Window queried, ending now |
| `CLOUDWATCH_MCP_COMMAND` / `_COMMAND_ARGS` | `uv` / see above | stdio launcher |

The language model is the same as for the other agents (`OPENAI_MODEL`).

No AWS credentials are written in the code or in `.env`:
- **locally**, use a profile that assumes a read-only role;
- **on AWS**, leave `CLOUDWATCH_MCP_AWS_PROFILE` empty, and the server uses the default
  credential chain, which is the IAM role of the ECS task or the instance.

## IAM permissions (least privilege)

The policy below lists exactly the permissions documented by AWS Labs. It contains no
configuration write: `logs:StopQuery` only stops a Logs Insights query, and the matching tool is
not allowlisted anyway.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "cloudwatch:DescribeAlarms",
      "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
      "logs:DescribeLogGroups", "logs:DescribeQueryDefinitions",
      "logs:ListLogAnomalyDetectors", "logs:ListAnomalies",
      "logs:StartQuery", "logs:GetQueryResults", "logs:StopQuery"
    ],
    "Resource": "*"
  }]
}
```

In production, `logs:StartQuery` can be restricted to the ARNs of the relevant log groups.

This was verified on the demo role: `SetAlarmState`, `CreateLogGroup`, and `FilterLogEvents`
return `AccessDenied`.

## Demo environment

`apps/api/scripts/seed_cloudwatch_demo.py` creates a synthetic incident. It uses an
administrator profile **during setup only**, and creates:
- the log group `/incidentflow/demo/payment-service` (1-day retention), with HTTP 500 and
  `MongoTimeoutError` events;
- the `IncidentFlow/Demo` metrics `HTTP5xxCount` and `LatencyP95Ms`;
- the alarm `incidentflow-demo-payment-5xx`;
- the role `IncidentFlowCloudWatchReadOnly`;
- the AWS CLI profile `incidentflow`, which assumes this role without any new access key.

Every resource is tagged `project=incidentflow`. The cost is below $1 per month.

```powershell
cd apps/api
.venv\Scripts\python scripts\seed_cloudwatch_demo.py --profile default --region us-east-1
.venv\Scripts\python scripts\seed_cloudwatch_demo.py --logs-only --minutes-ago 30   # refresh logs
.venv\Scripts\python scripts\seed_cloudwatch_demo.py --teardown                      # delete everything
```

Logs Insights ignores events dated before the log group was created. On the first run, the
synthetic logs are therefore packed into the seconds after creation. Running `--logs-only` later
produces a longer timeline.

## Commands

```powershell
cd apps/api
# 1. Check the tools actually exposed by the installed server
.venv\Scripts\python scripts\discover_cloudwatch_mcp_tools.py
# 2. Unit tests (mocks, no AWS)
.venv\Scripts\python -m pytest tests/test_cloudwatch_agent.py tests/test_cloudwatch_mcp_client.py
# 3. Live integration tests (skipped by default)
$env:INCIDENTFLOW_RUN_AWS_TESTS = "1"; .venv\Scripts\python -m pytest tests/test_cloudwatch_live_integration.py
```

## Docker Compose

The API image installs `awslabs.cloudwatch-mcp-server==0.3.1` at build time in its own virtual
environment (`/opt/cloudwatch-mcp`), so no PyPI download happens during an investigation.
`docker-compose.yml` points `CLOUDWATCH_MCP_COMMAND` at that executable, overriding the host `uv`
settings from `apps/api/.env`.

AWS credentials are not mounted by default. To give the container the local `incidentflow`
profile, set `AWS_CONFIG_DIR` in the root `.env` (for example `C:/Users/<you>/.aws`) and add the
opt-in override file:

```powershell
docker compose -f docker-compose.yml -f docker-compose.cloudwatch.yml up --build -d
```

The directory is mounted read-only at `/home/incidentflow/.aws`. Without the override file, the
agent reports `unavailable` and the investigation continues with the other specialists. On a
Linux container, uvicorn's event loop supports subprocesses, so the stdio MCP server starts from
the API; this is the recommended way to run the agent through the web application on Windows.

## End-to-end example

Request sent to the workflow:

> Investigate why payment-service has been returning HTTP 500 errors for about an hour.

Actual result on the demo environment, with Jira, MongoDB, and GitHub disabled:

1. The supervisor calls `ask_cloudwatch`, then consults the knowledge base for procedures.
2. The CloudWatch agent reads the alarm `incidentflow-demo-payment-5xx` (state ALARM), the
   `HTTP5xxCount` metric (from 0–1 to 40–70 errors per minute), and the logs, which contain
   `MongoTimeoutError … connection pool (maxPoolSize=20)`.
3. The hypothesis is MongoDB connection-pool exhaustion. It cites
   `logs:/incidentflow/demo/payment-service`, with an estimated confidence of 0.9.
4. The final report contains the `live` CloudWatch evidence, the hypothesis, and proposed
   actions (check the pool configuration, MongoDB health, and so on). None of them is executed.

## Known limitations

- **Docker credentials:** the opt-in `docker-compose.cloudwatch.yml` mounts the whole host
  `~/.aws` directory. The `incidentflow` profile assumes the read-only role, but its
  `source_profile` keys are also visible inside the container. For least privilege, give the
  source profile an IAM user whose only permission is `sts:AssumeRole` on
  `IncidentFlowCloudWatchReadOnly`.
- **Windows, API run on the host:** async psycopg requires a `SelectorEventLoop`, which does not
  support subprocesses. The stdio MCP server therefore cannot start from uvicorn on a Windows
  host; GitHub has the same limit. Scripts and tests use the default loop and work.
- **Fixed window:** the agent always reads the last `CLOUDWATCH_MCP_LOOKBACK_MINUTES` minutes.
  An incident that ended earlier (for example yesterday) cannot be investigated without raising
  this value. The window actually queried is reported in `time_window`.
- **Composite alarms:** they are read, but only metric alarms are followed up with their
  metric.
- **Volume:** each evidence block is truncated to 6,000 characters, and the log query returns at
  most 50 events.
- **Start-up:** each delegation starts the MCP server again, which adds a few seconds.
