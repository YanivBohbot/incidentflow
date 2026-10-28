# Durable investigations, human approval, and bounded memory

## Intent

IncidentFlow must preserve an investigation while an operator reviews a sensitive
Jira action. It must never let an agent approve its own work, and it must not
turn unverified LLM output or raw operational data into permanent memory.

## Goals

- Persist short-term investigation state so an interrupted workflow can resume
  after an API restart.
- Keep human approval mandatory for Jira ticket creation and Jira comments.
- Preserve the existing proposal audit trail: proposal, actor, decision,
  timestamps, and execution result.
- Add only curated, explicitly approved incident lessons to long-term memory.
- Keep all external integration reads least-privilege and all writes scoped to
  Jira ticket creation and comment creation.

## Non-goals

- No Jira issue editing, deletion, transition, or automatic remediation.
- No automatic long-term memory from chats, raw logs, tool output, or model
  hypotheses.
- No direct `approve` or `reject` tool available to any agent.

## Current state

The application already gives every investigation a `workflow_thread_id`, but
the LangGraph workflow is compiled without a checkpointer. The current Jira
proposal service persists PENDING, EXECUTING, EXECUTED, FAILED, REJECTED, and
CANCELLED states,
and executes Jira writes only after an API approval endpoint is used.

## Design

### Short-term memory: PostgreSQL checkpointer

Use a persistent LangGraph PostgreSQL checkpointer, configured with a dedicated
connection setting. Compile the investigation workflow with this checkpointer
and always invoke or resume it with the existing investigation
`workflow_thread_id`. This is the source of truth for graph state, messages,
interrupts, and durable resumption. The relational investigation record remains
the source of truth for the product-facing investigation lifecycle and report.

### Human-in-the-loop Jira actions

The first increment creates only two *proposals* through the existing UI/API:
`propose_jira_issue` and `propose_jira_comment`. They create an auditable draft
but never call Jira MCP directly. A later agent-generated draft may reuse these
same proposal contracts, but it cannot bypass the review workflow. Before the
application executes the corresponding `createJiraIssue` or
`addOrEditJiraIssueComment` MCP operation, the graph creates an interrupt
containing the proposed payload, incident and investigation IDs, evidence
references, and the action type. The UI displays it to an authenticated operator.
Approve, reject, or edit are API/UI decisions; they are not agent tools. The
decision endpoint resumes the same graph thread. Only an approved payload is
executed, while a rejection ends the pending action without a Jira write.

The existing `JiraActionProposal` database record remains the audit record and
idempotency guard. The LangGraph interrupt and the proposal must reference each
other by ID so that an approved action cannot execute twice.

### Long-term memory: curated incident lessons

Long-term memory is a separate Pinecone namespace, for example
`resolved_incidents`, not the current runbook namespace. A lesson can be
created only after an operator marks a completed investigation as confirmed.
It stores a concise approved summary, confirmed root cause, validated resolution,
source investigation ID, service, environment, timestamp, and future tenant ID.
It must never contain raw secrets, customer data, unverified hypotheses, or raw
tool output. Retrieval is read-only and metadata-filtered by tenant, service,
environment, and approval status.

## Guardrails

- Rename the external-content boundary to `ExternalEvidenceBoundaryMiddleware`.
  It must preserve the rule that external text is evidence, not instructions,
  and it must also protect manually collected GitHub MCP evidence.
- Keep repository allowlists and read-only MCP allowlists.
- Apply `ToolRetryMiddleware` only to idempotent read operations.
- Apply `PIIMiddleware` only after an explicit data-classification policy defines
  which fields must be redacted.
- Require evidence references on any Jira proposal.
- Bound MongoDB query windows, result volume, and allowed collections before
  exposing additional operational query tools.

## Acceptance criteria

1. An interrupted Jira proposal survives an API restart and can be resumed with
   the same thread ID.
2. No Jira MCP write occurs before an authenticated human approves it.
3. A rejected or cancelled proposal cannot execute later.
4. A duplicate approval cannot create a second Jira mutation.
5. A long-term lesson is retrievable only after explicit confirmation and only
   within its matching metadata scope.
6. Tests cover approval, rejection, duplicate resume, restart persistence, and
   memory isolation.
