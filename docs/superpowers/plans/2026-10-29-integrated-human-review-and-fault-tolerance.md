# Integrated Human Review and Fault Tolerance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pause an IncidentFlow investigation only when a validated human review is required, resume the same durable LangGraph thread, and recover safely from transient external failures.

**Architecture:** Extend the primary investigation `StateGraph` with optional, JSON-serializable human-review fields. The Supervisor proposes structured review data; deterministic policy decides whether it may interrupt. The investigation record is the product lifecycle source of truth, the PostgreSQL checkpointer preserves graph state, and the existing Jira proposal table remains the one-time write guard.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, LangGraph `StateGraph`, `interrupt`, `Command`, `PostgresSaver`, LangChain, React/TypeScript, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-29-integrated-human-review-and-fault-tolerance-design.md`

## Global Constraints

- Use the existing `investigation:<uuid>` thread; do not create a second Jira workflow thread.
- Human decisions are API/UI input, never LLM tools.
- Interrupt and resume payloads are JSON-serializable.
- Jira writes remain issue creation or comment creation and require approval.
- Never automatically retry a Jira mutation with an unknown outcome.
- Retry only idempotent, read-only transient failures with a bounded `RetryPolicy`.
- Do not store raw exceptions, credentials, or provider internals in State or HTTP responses.
- Preserve the existing Jira proposal claim-before-execute guard.

## Review Focus

- A report without a review recommendation completes without an interrupt; Task 3 tests this.
- A malformed or unsupported recommendation cannot pause or write; Task 2 tests this.
- A restarted API resumes the existing investigation thread; Task 4 tests this.
- A second approval cannot create a second Jira mutation; Task 4 tests this.
- A Jira write timeout is never retried automatically; Task 5 tests this.

---

### Task 1: Define review contracts and durable investigation lifecycle

**Files:**
- Create: `apps/api/src/incidentflow/domain/human_review/__init__.py`
- Create: `apps/api/src/incidentflow/domain/human_review/models.py`
- Modify: `apps/api/src/incidentflow/agent/agents_specialist/contracts.py`
- Modify: `apps/api/src/incidentflow/domain/investigations/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/investigation_repository.py`
- Create: `apps/api/alembic/versions/<revision>_add_pending_human_review_to_investigations.py`
- Test: `apps/api/tests/test_human_review_models.py`
- Test: `apps/api/tests/test_investigation_repository.py`

**Interfaces:**
- Produces `HumanReviewType`: `JIRA_WRITE`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`.
- Produces Pydantic `HumanReviewRecommendation`, `HumanReviewRequest`, and `HumanReviewDecision`.
- Extends `InvestigationReport` with `review_recommendation: HumanReviewRecommendation | None`.
- Extends `InvestigationLifecycle` with `AWAITING_HUMAN_REVIEW`.
- Extends `Investigation` with `pending_human_review: HumanReviewRequest | None`.

- [ ] **Step 1: Write failing domain and repository tests**

```python
def test_pending_review_round_trips_through_repository() -> None:
    awaiting = repository.mark_awaiting_human_review(investigation.id, report, review)
    assert awaiting.lifecycle is InvestigationLifecycle.AWAITING_HUMAN_REVIEW
    assert awaiting.pending_human_review == review
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_human_review_models.py tests/test_investigation_repository.py -q`

Expected: FAIL because review models, lifecycle, and repository method do not exist.

- [ ] **Step 3: Implement the contracts and migration**

Add nullable JSON `pending_human_review_payload` to `investigations`; map it only through `HumanReviewRequest`. Clear it on final completion or failure.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_human_review_models.py tests/test_investigation_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: add durable human review contracts"`

### Task 2: Add deterministic review and failure policies

**Files:**
- Create: `apps/api/src/incidentflow/agent/orchestration/review_policy.py`
- Create: `apps/api/src/incidentflow/agent/orchestration/failure_policy.py`
- Modify: `apps/api/src/incidentflow/agent/orchestration/states/investigation.py`
- Test: `apps/api/tests/test_review_policy.py`
- Test: `apps/api/tests/test_failure_policy.py`

**Interfaces:**
- Produces `build_human_review_request(report: InvestigationReport) -> HumanReviewRequest | None`.
- Produces `WorkflowFailure` with safe code, node, retryable flag, and public message.
- Produces `classify_node_failure(node_name: str, error: BaseException) -> WorkflowFailure`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_only_supported_recommendations_with_evidence_become_review_requests() -> None: ...
def test_provider_exception_becomes_safe_failure_without_raw_text() -> None: ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_review_policy.py tests/test_failure_policy.py -q`

Expected: FAIL because policy modules do not exist.

- [ ] **Step 3: Implement deterministic policy helpers**

Allow only the three named review types. Require non-empty evidence references for Jira review. Never treat an LLM recommendation as authorization. Keep failure classification outside graph code.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_review_policy.py tests/test_failure_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: add human review and failure policies"`

### Task 3: Add conditional interrupt and recovery routing to the main graph

**Files:**
- Modify: `apps/api/src/incidentflow/agent/orchestration/investigation_workflow.py`
- Delete: `apps/api/src/incidentflow/agent/orchestration/jira_action_workflow.py`
- Delete: `apps/api/src/incidentflow/agent/orchestration/states/jira_action.py`
- Modify: `apps/api/src/incidentflow/main.py`
- Test: `apps/api/tests/test_investigation_workflow.py`
- Delete: `apps/api/tests/test_jira_action_workflow.py`

**Interfaces:**
- Produces `build_investigation_workflow(supervisor=None, *, checkpointer=None, action_executor=None)`.
- Adds `human_review`, `execute_approved_action`, `record_review_rejection`, and `request_more_information` nodes.
- `human_review(state) -> Command` calls `interrupt()` and routes from `HumanReviewDecision`.

- [ ] **Step 1: Write failing workflow tests**

```python
def test_report_without_review_request_finishes_normally() -> None: ...
def test_valid_review_request_interrupts_main_thread() -> None: ...
def test_resumed_rejection_never_executes_action() -> None: ...
```

- [ ] **Step 2: Verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_investigation_workflow.py -q`

Expected: FAIL because the graph has no review branch.

- [ ] **Step 3: Implement the graph**

Attach bounded read-only `RetryPolicy` and a `NodeError` handler to the Supervisor node. Keep `human_review` free of side effects before `interrupt()`. Use `Command(goto=...)` for approve, reject, and information-request routes. Stop compiling the separate Jira action graph.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_investigation_workflow.py tests/test_checkpoint_lifecycle.py tests/test_main.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: integrate human review into investigation workflow"`

### Task 4: Resume investigations through the API and preserve Jira audit semantics

**Files:**
- Modify: `apps/api/src/incidentflow/application/services/investigation_service.py`
- Modify: `apps/api/src/incidentflow/api/routes/investigations.py`
- Modify: `apps/api/src/incidentflow/api/routes/jira.py`
- Modify: `apps/api/src/incidentflow/application/services/jira_approval_service.py`
- Test: `apps/api/tests/test_investigation_service.py`
- Test: `apps/api/tests/test_investigation_routes.py`
- Test: `apps/api/tests/test_jira_proposal_decisions.py`

**Interfaces:**
- Produces `InvestigationService.resume_human_review(investigation_id: UUID, decision: HumanReviewDecision) -> Investigation`.
- Produces `POST /api/investigations/{investigation_id}/human-review/resolve`.
- Resumes only `AWAITING_HUMAN_REVIEW` investigations using their persisted thread ID.

- [ ] **Step 1: Write failing service and route tests**

```python
def test_resume_uses_existing_investigation_thread_id() -> None: ...
def test_second_approval_has_no_second_jira_execution() -> None: ...
def test_rejection_clears_pending_review_without_jira() -> None: ...
```

- [ ] **Step 2: Verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_investigation_service.py tests/test_investigation_routes.py tests/test_jira_proposal_decisions.py -q`

Expected: FAIL because no review-resume endpoint exists.

- [ ] **Step 3: Implement resume and execution boundaries**

Resume with `Command(resume=decision.model_dump(mode="json"))`. Validate edited Jira payload before proposal creation. Reuse the atomic claim-before-execute guard, without automatic retry of a Jira write. Persist complete, failed, or further-information lifecycle from graph output.

- [ ] **Step 4: Verify**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_investigation_service.py tests/test_investigation_routes.py tests/test_jira_proposal_decisions.py tests/test_jira_approval_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: resume human-reviewed investigations safely"`

### Task 5: Render and resolve pending review in the investigations UI

**Files:**
- Create: `apps/web/src/features/investigations/HumanReviewPanel.tsx`
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/hooks/useIncidentFlow.ts`
- Modify: `apps/web/src/pages/InvestigationsPage.tsx`
- Modify: `apps/web/src/App.css`
- Test: `apps/web/src/features/investigations/HumanReviewPanel.test.tsx`
- Test: `apps/web/src/pages/InvestigationsPage.test.tsx`

**Interfaces:**
- Produces `HumanReviewPanel({ investigation, onResolve })`.
- Adds `api.resolveHumanReview(investigationId, decision)`.
- Adds `useIncidentFlow.resolveHumanReview(decision)`.

- [ ] **Step 1: Write failing UI tests**

```tsx
it('shows review data only for an awaiting investigation', () => { ... })
it('submits an explicit decision without auto-approving', async () => { ... })
```

- [ ] **Step 2: Verify failure**

Run: `npm test -- HumanReviewPanel InvestigationsPage`

Expected: FAIL because no review panel or client exists.

- [ ] **Step 3: Implement the review panel**

Show the reason, evidence references, editable permitted Jira fields, and explicit approve/reject/request-information controls. Do not expose raw checkpoints or default to approval. Refresh the investigation after resolution.

- [ ] **Step 4: Verify**

Run: `npm test -- HumanReviewPanel InvestigationsPage`

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: add investigation human review interface"`

### Task 6: Run end-to-end regression and safety checks

**Files:**
- Modify: `docs/VERIFICATION.md`
- Test: `apps/api/tests/test_investigation_api_integration.py`
- Test: `apps/api/tests/test_jira_approval_service.py`

- [ ] **Step 1: Add regression coverage**

Cover normal completion, paused/restarted/resumed review, rejection, exhausted read retry, and failed Jira write with no auto-retry.

- [ ] **Step 2: Verify backend**

Run: `$env:LANGSMITH_TRACING='false'; .\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS.

Run: `.\.venv\Scripts\python.exe -m ruff check src tests`

Expected: PASS.

- [ ] **Step 3: Verify frontend**

Run: `npm run lint`

Expected: PASS.

Run: `npm run build`

Expected: PASS.

- [ ] **Step 4: Record verified results and commit**

Update `docs/VERIFICATION.md` only with commands actually run. Do not record live Jira writes unless separately authorized and performed.

`git commit -m "test: verify integrated human review workflow"`

