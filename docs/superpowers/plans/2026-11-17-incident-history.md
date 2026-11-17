# Incident History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every incident/investigation event as it happens and show a decision timeline plus a per-incident journal in a new History tab.

**Architecture:** New `incident_events` table with an `IncidentEventRepository`; services append an event right after their committed state change (worker events only after a successful fenced write). Read-only `/api/history` and `/api/incidents/{id}/events` routes feed a new React `HistoryPage`. A manual idempotent script backfills past events marked `reconstructed`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, pytest (SQLite), React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-17-incident-history-design.md`

## Global Constraints

- Do not change the "Recent investigations" list (`InvestigationsPage` left column) or the metric cards in `App.tsx`.
- Ruff 100-char lines; type annotations; `test_<behavior>` names; no persistence logic in routers.
- Times are UTC; SQLite drops tz in tests, so repositories normalise to UTC on read (existing pattern).
- Event kinds (exact strings): `INCIDENT_CREATED`, `INVESTIGATION_STARTED`, `REVIEW_REQUESTED`, `REVIEW_DECIDED`, `INVESTIGATION_COMPLETED`, `INVESTIGATION_FAILED`, `INCIDENT_RESOLVED`, `INCIDENT_CLOSED`, `LESSON_SAVED`, `DEMO_RUN_STARTED`.
- Actors: principal username, or `system`, `demo`, `unknown` (backfill only).
- `/api/history` default `limit` 50, max 200; newest first. `/api/incidents/{id}/events` oldest first.
- "Decisions only" filter = `REVIEW_DECIDED`, `INCIDENT_RESOLVED`, `LESSON_SAVED`.
- Event write rule (refines the spec, which said "same transaction"): repositories commit on their own, so an event is appended **right after** the committed change. A crash between the two can lose one event; an event is never written for a change that did not happen.
- Migration revision named `add_incident_events`, `down_revision = "b4d6f8a0c2e4"`.

## Review Focus

- Refused actions (409 already active, 404, resolving an already-resolved incident, demo run refused) must write **no** event.
- A lost lease / redelivered completion (`persist_workflow_result` raising `LeaseLostError`) must write **no** event; a successful one exactly one.
- Deleting an incident that has events must still return 204 (FK `ON DELETE CASCADE`).
- `before` pagination with several events at the same `occurred_at` must not drop or repeat rows (order by `occurred_at DESC, id DESC`; `before` is a cursor `<occurred_at>|<id>`).
- Running the backfill twice inserts nothing the second time.

---

### Task 1: Event model, table, repository

**Files:**
- Create: `apps/api/src/incidentflow/domain/history/__init__.py`, `apps/api/src/incidentflow/domain/history/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/models.py` (add `IncidentEventORM`)
- Create: `apps/api/src/incidentflow/infrastructure/database/incident_event_repository.py`
- Create: `apps/api/alembic/versions/<rev>_add_incident_events.py`
- Test: `apps/api/tests/test_incident_event_repository.py`

**Interfaces:**
- Produces:
  - `IncidentEventKind(str, Enum)` with the 10 kinds; `DECISION_KINDS: frozenset[IncidentEventKind]`.
  - `IncidentEvent(BaseModel)`: `id: UUID, incident_id: UUID | None, investigation_id: UUID | None, kind: IncidentEventKind, occurred_at: datetime, actor: str, summary: str (≤300), details: dict[str, Any], reconstructed: bool, incident_title: str | None = None`.
  - `IncidentEventPage(BaseModel)`: `events: list[IncidentEvent], next_before: str | None`.
  - `IncidentEventRepository(session)`:
    - `record(kind, *, incident_id=None, investigation_id=None, actor="system", summary, details=None, occurred_at=None, reconstructed=False) -> IncidentEvent` (commits).
    - `list_history(*, incident_id=None, kinds=None, before: str | None = None, limit=50) -> IncidentEventPage` (joins incident title).
    - `list_for_incident(incident_id) -> list[IncidentEvent]` (oldest first).
    - `has_events_for_incident(incident_id) -> bool`.

- [ ] **Step 1: Write failing tests** — `test_record_and_list_history_newest_first`, `test_history_filters_by_incident_and_kinds`, `test_before_cursor_pages_without_gaps_or_repeats` (5 events, 3 sharing one `occurred_at`, `limit=2` → pages cover all 5 once, last `next_before` is None), `test_incident_journal_is_oldest_first`, `test_history_rows_carry_the_incident_title`, `test_deleting_an_incident_deletes_its_events` (enable SQLite FKs with `PRAGMA foreign_keys=ON` in the fixture).
- [ ] **Step 2: Run** `pytest tests/test_incident_event_repository.py -q` → FAIL (import error).
- [ ] **Step 3: Implement** ORM (`incident_events`, FKs `ondelete="CASCADE"` to incidents, `ondelete="SET NULL"` to investigations, JSON `details`, indexes on `occurred_at` and `(incident_id, occurred_at)`), models, repository, migration (`alembic revision -m "add_incident_events"`, set `down_revision`).
- [ ] **Step 4: Run** tests → PASS; `alembic upgrade head` against the compose DB succeeds (`docker compose run --rm migrate`).
- [ ] **Step 5: Commit** `Add incident events table and repository`.

### Task 2: API-side event writers

**Files:**
- Modify: `application/services/incident_service.py`, `incident_ingestion_service.py`, `investigation_service.py`, `demo_service.py`, `incident_lesson_service.py`; `infrastructure/database/incident_repository.py` (`close_open_alarm_incidents` returns `list[UUID]`); routes `api/routes/incidents.py`, `investigations.py`, `demo.py`, `incident_lessons` route (wherever `confirm_and_index` is called) to pass `principal.username`.
- Test: `apps/api/tests/test_incident_event_writers.py`; update callers of `close_open_alarm_incidents` (demo service + tests use `len(...)`).

**Interfaces:**
- Consumes: `IncidentEventRepository.record` (Task 1).
- Produces: services take `events: IncidentEventRepository | None = None` (keyword) and methods take `actor: str = "system"` where an operator acts:
  - `IncidentService.create_incident(data, *, actor="system")`, `resolve_incident(incident_id, *, actor="system")` (event only when status actually changes to RESOLVED).
  - `IncidentIngestionService.ingest_cloudwatch_alarm(event)` → `INCIDENT_CREATED`, actor `system`, `details.source="CLOUDWATCH_ALARM"`, only when an incident is created.
  - `InvestigationService.start_investigation(data, *, actor="system")` → `INVESTIGATION_STARTED`; `request_human_review_resume(...)` → `REVIEW_DECIDED` with `details={"decision", "reason", "tool_name"}`, actor = decision actor, only after the resume is accepted.
  - `DemoService.start_run(only_if_idle=False, *, actor="demo")` → one `INCIDENT_CLOSED` per closed id (`details.run_id`) then `DEMO_RUN_STARTED` (`incident_id=None`, `details={"run_id","closed"}`), only when the run starts.
  - `IncidentLessonService.confirm_and_index(confirmation, *, actor="system")` → `LESSON_SAVED` only when state is CONFIRMED.

- [ ] **Step 1: Write failing tests**, one per writer plus refusals: `test_manual_incident_records_created_event_with_actor`, `test_alarm_ingestion_records_created_event_once` (duplicate alarm → still one), `test_start_records_event_and_conflict_records_none`, `test_resolve_records_event_once` (second resolve → no new event), `test_review_decision_records_actor_and_decision`, `test_demo_run_records_closed_and_started`, `test_refused_demo_run_records_nothing`, `test_confirmed_lesson_records_event_and_failed_index_does_not`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the writers; routes pass `actor=principal.username` (`OperatorPrincipal`); dependency factories build `IncidentEventRepository(session)`.
- [ ] **Step 4: Run** full suite `pytest -q` → PASS (existing demo tests updated for `close_open_alarm_incidents` returning ids).
- [ ] **Step 5: Commit** `Record incident events from API actions`.

### Task 3: Worker-side event writers

**Files:**
- Modify: `application/jobs/processor.py` (`persist_workflow_result`, deadline failure path)
- Test: `apps/api/tests/test_investigation_job_events.py`

**Interfaces:**
- Consumes: Task 1 repository.
- Produces: `persist_workflow_result(repository, claimed, result, *, events: IncidentEventRepository | None = None) -> Investigation`; after the fenced write succeeds it records:
  - `REVIEW_REQUESTED` (`details={"review_type", "tool_name"?, "summary"?}`),
  - `INVESTIGATION_COMPLETED` (`details={"confidence", "root_cause", "jira_key"?}`; `jira_key` = first `[A-Z][A-Z0-9]+-\d+` found in the report evidence from the Jira specialist (`sourceKey`-style match on "it_operations"/"jira"), only when that investigation has an approved `REVIEW_DECIDED` event),
  - `INVESTIGATION_FAILED` (`details={"error"}`); the deadline path records it too.
  All with `incident_id` from the claimed investigation, actor `system`.

- [ ] **Step 1: Write failing tests**: `test_completion_records_one_event_with_confidence`, `test_completion_after_approved_jira_write_carries_the_issue_key`, `test_pause_records_review_requested`, `test_failure_records_failed_with_error`, `test_lost_lease_records_no_event` (fenced write returns None → `LeaseLostError`, no event).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `Record incident events from the worker`.

### Task 4: History API

**Files:**
- Create: `apps/api/src/incidentflow/api/routes/history.py`; register in `main.py` under `/api`.
- Test: `apps/api/tests/test_history_routes.py`

**Interfaces:**
- Produces: `GET /api/history?incident_id=&kinds=A,B&before=&limit=` → `IncidentEventPage` (viewer); unknown kind → 422; `limit` clamped 1..200.
  `GET /api/incidents/{id}/events` → `list[IncidentEvent]` (viewer); unknown incident → 404. Put this route in `history.py` (prefix-less router) to keep incidents routes untouched.

- [ ] **Step 1: Failing tests**: `test_viewer_reads_history_newest_first`, `test_history_filters_and_paginates`, `test_unknown_kind_is_422`, `test_incident_journal_route_and_404`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; `ruff check src tests scripts`.
- [ ] **Step 5: Commit** `Add history API`.

### Task 5: Backfill script

**Files:**
- Create: `apps/api/scripts/backfill_incident_events.py` (callable `backfill(session, *, trace_reader=None) -> int`, CLI `python scripts/backfill_incident_events.py`).
- Test: `apps/api/tests/test_backfill_incident_events.py`

**Interfaces:**
- Consumes: Task 1 repository (`has_events_for_incident`, `record(..., reconstructed=True, occurred_at=...)`).
- Produces: per incident without events, rows as listed in the spec "Backfill" section; review events from `trace_reader(investigation_id) -> list[InvestigationTraceStep]` (the CLI wires `InvestigationService.get_investigation_trace` with the Postgres checkpointer; tests pass a fake).

- [ ] **Step 1: Failing tests**: `test_backfill_reconstructs_incident_journal` (manual incident + completed investigation + resolved + lesson → expected kinds in order, all `reconstructed`, actor `unknown` for resolution), `test_backfill_adds_review_events_from_the_trace`, `test_second_backfill_inserts_nothing`, `test_backfill_skips_incidents_that_already_have_events`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add incident event backfill script`.

### Task 6: History tab (web)

**Files:**
- Modify: `apps/web/src/api.ts` (types `IncidentEvent`, `IncidentEventPage`; `api.getHistory(params)`, `api.getIncidentEvents(id)`), `components/layout/AppShell.tsx` (`AppPage` adds `'history'`, nav item after Approvals), `App.tsx` (route + `openJournal(incidentId)` state; metric cards untouched), `pages/IncidentsPage.tsx` (selected incident: "View journal" button), `pages/InvestigationsPage.tsx` (resolve banner only: "View journal"), `index.css`.
- Create: `apps/web/src/pages/HistoryPage.tsx`, `apps/web/src/pages/HistoryPage.test.tsx`

**Interfaces:**
- Consumes: Task 4 endpoints.
- Produces: `HistoryPage({ incidents, initialIncidentId?, onOpenInvestigation })`; `IncidentsPage`/`InvestigationsPage` get optional `onViewJournal?: (incidentId: string) => void`.

- [ ] **Step 1: Failing tests**: `renders the chronology newest first with incident titles`, `decisions-only chip filters to decision kinds` (asserts `getHistory` called with the 3 kinds), `selecting an event shows that incident's journal oldest first`, `reconstructed events show ≈ before the time`, `load more requests the next page with before`, `open investigation calls onOpenInvestigation`, plus in existing page tests: `View journal calls onViewJournal with the incident id`.
- [ ] **Step 2: Run** `npx vitest run` → FAIL. **Step 3: Implement** (poll every 10 s while visible, like the workspace). **Step 4: Run** vitest, `npm run lint`, `npm run build` → PASS.
- [ ] **Step 5: Commit** `Add History tab with decision timeline and incident journal`.

### Task 7: Live check and docs

- [ ] Rebuild (`docker compose -f docker-compose.yml -f docker-compose.cloudwatch.yml up --build -d --force-recreate --no-deps api worker web`), run `migrate`, run the backfill in the api container, confirm via `docker exec ... grep` that new code is deployed.
- [ ] Run a demo, one investigation with a Jira approval, resolve, save a lesson; check `/api/incidents/{id}/events` lists every step in order with actors, and the History tab shows them.
- [ ] Add a short "History" section to `README.md` (what is recorded, the backfill command). Commit `Document incident history`.
