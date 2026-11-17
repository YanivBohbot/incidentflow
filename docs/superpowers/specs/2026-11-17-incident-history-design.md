# Incident history: decision timeline and incident journal

Date: 2026-11-17. Status: proposed.

## Intent

Operators want to look back and see **what was done**: a chronology of the decisions taken
across all incidents, and a journal per incident (alarm → investigations → reviews → Jira ticket
→ resolution → lesson). Today this only exists scattered across investigation traces; the exact
time of a resolution, who decided, and "closed by the demo" vs "resolved by an operator" are
not recorded at all.

## Goals

1. A new **History** tab in the sidebar with two columns: a global chronology of events (newest
   first, filterable) and, for the selected incident, its journal (oldest first).
2. Every product event is **recorded when it happens**, with its time, actor, and a short detail.
3. Past data is **reconstructed once**, as far as it can be, and marked "reconstructed".
4. One-click links: "View journal" from the selected incident (Incidents page) and from a
   completed investigation (Investigations page); from a journal event, open its investigation.

## Non-goals

- Editing or deleting events; export; retention policies; multi-tenant scoping.
- A separate "demo runs" page (a demo run is one event in the chronology).
- Real-time push (the page polls like the rest of the dashboard).

## Anti-goals

- Changing the "Recent investigations" list or the metric cards at the top (owner's constraint).
- Recording an event for a change that did not happen (e.g. a lease-lost worker write), or
  recording one event twice for the same transition (job redelivery).
- Presenting reconstructed times as exact.

## Approaches considered

- **A. Events recorded as they happen + one-time backfill (chosen by the owner).** New table,
  written by the services at each action; the page reads it. Exact order, actor known, fast.
- B. Recompute the journal on every read from incidents, investigations and checkpoints. No
  migration, but slow (checkpoints of every investigation), resolution time still wrong, actor
  and "closed by demo" unknown. Rejected: it does not fix what is missing.
- (Dropped) External log store such as CloudWatch Logs: too heavy for an in-app page and does
  not behave the same locally.

## Design

### Data: `incident_events` (new Alembic revision `add_incident_events`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `incident_id` | UUID FK → incidents, nullable, `ON DELETE CASCADE` | null only for `DEMO_RUN_STARTED`; deleting an incident deletes its journal (my call: the delete endpoint must keep working) |
| `investigation_id` | UUID FK → investigations, nullable | |
| `kind` | string enum | see below |
| `occurred_at` | timestamptz (UTC) | server time of the transition |
| `actor` | string | principal username, or `system`, `demo`, `unknown` (backfill) |
| `summary` | string ≤ 300 | one human sentence shown in the UI |
| `details` | JSON | kind-specific: `jira_key`, `confidence`, `root_cause`, `decision`, `reason`, `run_id`, `error`, `source` |
| `reconstructed` | bool, default false | true for backfilled rows |

Indexes: `(occurred_at DESC)`, `(incident_id, occurred_at)`.

Kinds and where they are written. Repositories commit on their own, so an event is appended right
after the committed state change: a crash in between can lose one event, but an event is never
written for a change that did not happen:

| Kind | Written by | Actor |
|---|---|---|
| `INCIDENT_CREATED` | `IncidentService.create_incident` (manual), `IncidentIngestionService` (alarm; `details.source`) | principal / `system` |
| `INVESTIGATION_STARTED` | `InvestigationService.start_investigation` | principal |
| `REVIEW_REQUESTED` | `persist_workflow_result` when it marks AWAITING_HUMAN_REVIEW (Jira write or report review; draft summary) | `system` |
| `REVIEW_DECIDED` | `InvestigationService` when resolving a review (APPROVE / REJECT / REQUEST_INFORMATION, reason) | decision actor (verified principal when auth is on) |
| `INVESTIGATION_COMPLETED` | `persist_workflow_result` on completion (`root_cause`, `confidence`, `jira_key` if a Jira issue was created) | `system` |
| `INVESTIGATION_FAILED` | `persist_workflow_result` / processor deadline (`error`) | `system` |
| `INCIDENT_RESOLVED` | `IncidentService.resolve_incident` (only on an actual status change) | principal |
| `INCIDENT_CLOSED` | `DemoService.start_run` closing previous demo incidents (`run_id`); `close_open_alarm_incidents` returns the closed ids instead of a count (my call) | `demo` |
| `LESSON_SAVED` | `IncidentLessonService.confirm_and_index` when state is CONFIRMED | principal |
| `DEMO_RUN_STARTED` | `DemoService.start_run` when a run starts (`run_id`, closed count) | principal / `demo` (auto-start) |

Worker-side events are written only when the fenced write succeeds (persisted row not None), so
a redelivered job or a lost lease does not duplicate or invent events. The principal is passed
from the routes into the services (routes already resolve it); services keep working without
one (`system`) for scripts and Lambdas.

`jira_key`: on completion after an approved Jira write, taken from the `createJiraIssue` tool
result in the run's messages (pattern `[A-Z][A-Z0-9]+-\d+`); absent if none. Builder's call how
to reach the messages (state at persist time or the trace builder).

### API

- `GET /api/history?incident_id=&kinds=A,B&before=<iso>&limit=50` (viewer): events newest first,
  each with `incident_title`; `before` paginates. Default `limit` 50, max 200.
- `GET /api/incidents/{id}/events` (viewer): that incident's journal, oldest first.
- Pydantic contract `IncidentEvent` in `domain/history/models.py`; repository
  `IncidentEventRepository`; router `api/routes/history.py`.

### Backfill (manual script, idempotent)

`apps/api/scripts/backfill_incident_events.py`, run once per environment (not in the test suite,
not in `migrate`): for every incident/investigation/lesson without events, insert
`reconstructed=true` rows:

- `INCIDENT_CREATED` at `incidents.created_at`; `INVESTIGATION_STARTED` at
  `investigations.created_at`; `INVESTIGATION_COMPLETED`/`FAILED` at `investigations.updated_at`.
- `REVIEW_REQUESTED`/`REVIEW_DECIDED` from the checkpoint state's resolved reviews (via the
  trace builder), time = investigation `updated_at` (approximate), actor from the decision.
- `INCIDENT_RESOLVED` / `INCIDENT_CLOSED` at `incidents.updated_at`, actor `unknown`
  (CLOSED → "closed", RESOLVED → "resolved"); `LESSON_SAVED` at the lesson's creation time.
- Skips an incident that already has events, so a second run inserts nothing.

### Web: History tab

- New sidebar item **History** (after Approvals); new page `pages/HistoryPage.tsx`.
- Left: chronology with filters (incident, event type; default all types, plus a "Decisions
  only" chip = `REVIEW_DECIDED`, `INCIDENT_RESOLVED`, `LESSON_SAVED`; my call, matching "a
  chronology of decisions"), newest first, "Load more" via `before`. Each row: icon, time, summary, incident title; "reconstructed" rows show an
  "≈" before the time.
- Right: journal of the selected incident (oldest first), vertical timeline like the agent trace;
  an event with an investigation has "Open investigation" (switches to Investigations with it
  selected). Empty state until an incident is chosen.
- Links: "View journal" on the selected incident (Incidents) and in the resolve banner of a
  completed investigation (Investigations, right panel only), opening History on that incident.
- Refresh every 10 s while the tab is visible (same as the workspace).

## Testing

- Repository: insert/list/order/pagination/filters on SQLite.
- Each writer: the event is written with the transition, not when the action is refused (409,
  404, already resolved, lease lost); redelivered completion writes one event.
- Routes: viewer can read, filters, 404 for unknown incident.
- Backfill: produces expected rows on a seeded SQLite DB; second run inserts nothing.
- Web: History page renders chronology and journal, filters, "≈" marker, links switch pages.
- Live check: run a demo + one investigation with Jira approval + resolve + lesson, then see the
  full journal in the tab.

## Left to the builder

Event icons and exact summary wording; how the principal reaches services (argument vs
dependency); reaching the run messages for `jira_key`; order of implementation.
