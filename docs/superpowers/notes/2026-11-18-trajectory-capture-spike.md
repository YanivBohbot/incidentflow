# Trajectory capture spike (2026-11-18)

Script: `apps/api/evaluation/spike_trajectory_capture.py` (throwaway). Scenario `EVAL-PAY-001`,
Jira/MongoDB/GitHub/CloudWatch MCP disabled (placeholder findings), Pinecone live,
`LANGSMITH_TRACING=true`, `InMemorySaver`. All three methods ran in one `astream` run, with the root
run id fixed through `config["run_id"]`.

## What each method captured

**(a) `BaseCallbackHandler.on_tool_start` in `config["callbacks"]`: 8 tool calls, nested included.**
Confirmed: `subagent_config` keeps the parent callbacks, so the Knowledge specialist's Pinecone calls
arrive in the same handler. Shape: `{name, inputs, run_id, parent_run_id}`, in start order:

```
ask_data_intelligence  inputs={'incident_context': 'Payment API HTTP 500 ...'}  parent=...4f04
ask_cloudwatch         inputs={'incident_context': ...}
ask_knowledge          inputs={'incident_context': ...}
search_incident_response_guides  inputs={'query': 'MongoDB pool timeout HTTP 500 errors Payment API'}  parent=...7319
ask_data_intelligence  (second supervisor turn)
ask_knowledge          (second supervisor turn)
search_incident_response_guides  inputs={'query': 'MongoDB connection pool exhaustion ...'}
search_confirmed_incidents       inputs={'query': ..., 'service': 'Payment API', 'environment': ...}
```

Both levels are present: the supervisor's `ask_*` tools and the specialist's `search_*` tools. The
tool inputs are a dict in `inputs=` (use it instead of `input_str`). Caveat: a nested tool's
`parent_run_id` is the specialist's internal tools-node chain run, not the `ask_knowledge` run id, so
nesting cannot be read from a direct parent link. Treat the order of the flat list as the trajectory
and mark nested calls by name (non-`ask_*`).

**(b) `astream(stream_mode="updates")`: node names only.** Path:
`validate -> prepare -> investigate -> capture_report -> finalize`. It shows no tool calls (the
supervisor runs inside the `investigate` node), so it covers the node path only.

**(c) `Client().list_runs(trace_id=root_run_id, run_type="tool")`: 8 tool runs, the same set as (a).**
Fields `name`, `id`, `parent_run_id` (inputs/outputs also available). It works only after the
tracers flush (`wait_for_all_tracers()` plus a short sleep), needs LangSmith credentials and
network, and the result order is not chronological. `list_runs` is deprecated in favour of
`client.runs.query()`.

## Interrupt and final state

`EVAL-PAY-001` has no interrupt: no `__interrupt__` chunk appeared in the updates stream, and
`aget_state(config).next == ()`. The final state values carry `report` (an `InvestigationReport`),
`investigation_lifecycle`, `errors`, `human_review`, `messages`, `structured_response`,
`workflow_stage`, and so on. `ainvoke` returns the same state, so `result["report"]` is present for this
scenario. For scenarios that do interrupt, `astream` emits a `{"__interrupt__": (Interrupt, ...)}`
chunk and `state.next` is non-empty; this was not exercised here.

## Decision

- Tool trajectory: a callback handler passed in `config["callbacks"]` (offline, no LangSmith
  dependency, includes nested specialist calls, includes `inputs`).
- Node path and `__interrupt__`: `astream(stream_mode="updates")`, which also gives the final state
  through `aget_state`.
- LangSmith run reads (c) are not needed for capture; keep them only as a cross-check.

## Concerns

- With `LANGSMITH_TRACING=true` and an explicit `run_id` in config, many
  `Error in LangChainTracer.on_chain_end callback: TracerException('No indexed run ID ...')` lines
  were printed. The runs were still uploaded (8 tool runs read back), so they are noise, but they
  may stem from the explicit `run_id`; Task 3 should not set `run_id` unless it needs the trace id.
- A checkpoint deserialization warning for `InvestigationReport` (unregistered msgpack type) appears
  on `aget_state`.
