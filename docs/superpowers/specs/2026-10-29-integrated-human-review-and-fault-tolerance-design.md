# Integrated human review and fault tolerance

## Intent

IncidentFlow must pause an investigation only when a validated policy requires a
human decision. A human reviewer must be able to approve, reject, or edit a
proposed sensitive action without losing the investigation state after an API
restart. Normal, read-only investigations must finish without interruption.

## Goals

- Make human review a conditional stage of the primary investigation workflow.
- Use LangGraph `interrupt()` and `Command(resume=...)` with the existing
  investigation `workflow_thread_id` and PostgreSQL checkpointer.
- Support an initial `JIRA_WRITE` review type and make future sensitive action
  types additive rather than requiring another workflow.
- Keep PostgreSQL as the auditable, idempotent source of truth for Jira writes.
- Add bounded retry and explicit recovery paths for transient read failures.
- Return safe, actionable failure states without exposing provider internals or
  raw secrets.

## Non-goals

- No agent may approve, reject, or execute a sensitive action.
- No automatic Jira mutation, deployment, remediation, or escalation.
- No automatic retry of an external write whose final outcome is unknown.
- No long-term-memory change: a paused workflow remains short-term checkpointed
  state, not a Pinecone incident lesson.

## Current state

The investigation graph currently ends after the Supervisor returns an
`InvestigationReport`. Jira proposals are manually prepared in the UI and use a
separate one-node interrupt graph. The current report has textual
`proposed_actions`, but no structured request describing whether human review is
required or what data a future action needs.

## Approaches considered

1. **Keep the separate Jira review graph.** This preserves the current UI but
   does not let the investigation itself request a review.
2. **Selected: add a conditional review stage to the investigation graph.** The
   Supervisor may propose structured review data; deterministic policy validates
   it before the graph pauses. The same investigation thread resumes into an
   explicit execute, reject, or information-request path.
3. **Invoke the existing Jira graph as a subgraph.** This appears reusable but
   makes restart and re-execution semantics harder to reason about. It is not
   needed for one primary workflow.

## Design

### One primary workflow and one bounded state

The investigation graph will use one `InvestigationWorkflowState`. It will keep
the existing request, lifecycle, report, and error fields, then add optional
review fields:

- `human_review`: a JSON-serializable `HumanReviewRequest` containing an ID,
  review type, reason, editable draft, and evidence references.
- `human_decision`: the human response, including approve, reject, request more
  information, or an edited draft.
- `action_result`: the safe outcome of an approved action when one is executed.

`HumanReviewRequest` and `HumanReviewDecision` remain small separate domain
models. This avoids an unbounded State while keeping the primary graph’s State
clear. The former standalone `JiraActionReviewState` and workflow will be
removed after the migration.

### Conditional review policy

The Supervisor contract will gain an optional structured review recommendation.
The application validates it before a pause; it does not treat a model request
as authority. Initial policy permits review only for:

- `JIRA_WRITE`, when a Jira issue or comment draft has valid evidence references.
- `INSUFFICIENT_EVIDENCE`, when the operator must provide missing context before
  the investigation can make a reliable conclusion.
- `CONFLICTING_EVIDENCE`, when evidence sources materially disagree and a human
  must choose how to proceed.

If no valid review request exists, the graph goes directly from Supervisor
output to report finalization. If one exists, it transitions to `human_review`.

### Human review and Jira execution

The `human_review` node calls `interrupt()` before any side effect. Its payload
contains the review ID, reason, editable draft, and evidence references. The
frontend renders the matching review form from this payload.

The review API resumes the *same* `investigation:<uuid>` thread with
`Command(resume=decision)`. The review node returns a `Command` that routes to
one of three explicit nodes:

- `execute_approved_action` validates an approved edited draft and executes the
  supported action.
- `record_review_rejection` records the operator decision without contacting an
  external provider.
- `request_more_information` stores the request and leaves the investigation in
  a reviewable state without creating a Jira action.

For `JIRA_WRITE`, the existing `JiraActionProposal` table remains the durable
audit and idempotency record. The action node atomically claims `PENDING` before
calling Jira and records `EXECUTED` or `FAILED` afterwards. Graph checkpoints
are workflow snapshots; they do not replace this database guard.

### API and frontend

Investigations gain a durable `AWAITING_HUMAN_REVIEW` lifecycle. Starting an
investigation returns either a completed/failed result or this pending state.
The UI adds an investigation review panel instead of requiring the operator to
navigate to a separate Jira workflow. It can display the draft, allow permitted
edits, and submit a decision through a resume endpoint.

Existing historical Jira proposals remain viewable. The manual proposal composer
is removed or retained only after migration compatibility is confirmed; it must
not create a second approval path for the same action.

### Fault tolerance and error handling

- Validation, schema, authorization, and policy failures are never retried;
  they route to a safe failed or review-needed state.
- Idempotent read-only nodes may use a bounded LangGraph `RetryPolicy` for
  transient connection failures, timeouts, rate limits, and retryable provider
  responses. Retries use a small maximum attempt count and backoff.
- The Supervisor node receives a node `error_handler` after retries are
  exhausted. It writes a safe error classification into State and routes to a
  final degraded report rather than losing the workflow.
- The Jira write node receives no automatic retry. A timeout after a remote
  mutation has an unknown outcome; the proposal remains auditable for an
  operator-led reconciliation instead of risking a duplicate ticket.
- Any code before `interrupt()` is pure or idempotent. Writes occur in explicit
  post-decision nodes only.
- Tests use provider doubles; live Jira is never required for fault tests.

## Acceptance criteria

1. A normal investigation with no valid review request reaches `COMPLETED`
   without an interrupt.
2. A valid Jira write request pauses the main investigation with a durable,
   JSON-serializable interrupt payload.
3. Restarting the API does not lose an awaiting review; the same thread resumes
   from its saved checkpoint.
4. Approval validates the edited payload and performs at most one Jira mutation.
5. Rejection, cancellation, and information requests never contact Jira.
6. A transient read failure retries only within its configured bound, then ends
   with a safe classified result.
7. A Jira write timeout is not automatically retried.
8. Unit, integration, regression, and frontend tests cover all branches.
