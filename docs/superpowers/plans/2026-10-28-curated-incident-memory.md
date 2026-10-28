# Curated Incident Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrieve similar confirmed incidents from a separate Pinecone namespace without persisting raw evidence, hypotheses, or conversation history as long-term memory.

**Architecture:** Keep the existing runbook index unchanged. Add a distinct `resolved_incidents` namespace containing only operator-confirmed lessons generated from completed investigations. The retrieval tool remains read-only and metadata-filtered by environment, service, approval status, and future tenant scope.

**Tech Stack:** Pinecone, LangChain Pinecone integration, Pydantic, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-durable-investigations-design.md`

## Global Constraints

- Never index raw logs, raw MCP results, messages, secrets, customer data, or unverified hypotheses.
- Index only an operator-confirmed root cause and validated resolution from a completed investigation.
- Do not mix resolved-incident memory with the runbook Pinecone namespace.
- Retrieval must always use metadata filters and a bounded result count.

## Review Focus

- An incomplete investigation cannot be confirmed or indexed; cover in Task 1.
- An unconfirmed lesson cannot be retrieved; cover in Task 2.
- A matching query outside the requested environment or tenant scope returns no lesson; cover in Task 2.
- A failed Pinecone upsert never marks a lesson confirmed; cover in Task 1.
- The existing runbook retrieval behavior remains unchanged; cover in Task 3.

---

### Task 1: Model and persist a confirmed incident lesson

**Files:**
- Create: `apps/api/src/incidentflow/domain/memory/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/models.py`
- Modify: `apps/api/src/incidentflow/infrastructure/database/base.py`
- Create: `apps/api/src/incidentflow/infrastructure/database/incident_lesson_repository.py`
- Create: `apps/api/alembic/versions/<revision>_add_incident_lessons.py`
- Create: `apps/api/tests/test_incident_lesson_repository.py`

**Interfaces:**
- Produces: `IncidentLessonConfirmation` with `investigation_id`, `service`, `environment`, `confirmed_root_cause`, and `validated_resolution`.
- Produces: `IncidentLesson` whose state is `PENDING_INDEX`, `CONFIRMED`, or `INDEX_FAILED`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_only_completed_investigations_create_pending_index_lessons() -> None:
    ...

def test_failed_index_does_not_mark_lesson_confirmed() -> None:
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_incident_lesson_repository.py -q`

Expected: FAIL because the lesson model and repository do not exist.

- [ ] **Step 3: Implement validated lesson persistence and migration**

Persist only approved fields, source investigation ID, timestamps, and scoped metadata. Do not add an automatic write path from the Supervisor.

- [ ] **Step 4: Verify and commit**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_incident_lesson_repository.py -q`

Commit: `feat: persist confirmed incident lessons`

### Task 2: Add scoped Pinecone indexing and retrieval

**Files:**
- Create: `apps/api/src/incidentflow/knowledge/resolved_incident_store.py`
- Modify: `apps/api/src/incidentflow/core/config.py`
- Create: `apps/api/src/incidentflow/agent/tools/resolved_incident_memory_tools.py`
- Create: `apps/api/tests/test_resolved_incident_memory_tools.py`

**Interfaces:**
- Produces: `index_confirmed_incident_lesson(lesson: IncidentLesson) -> str`.
- Produces: `search_confirmed_incidents(query: str, *, service: str, environment: str, tenant_id: str | None = None) -> str`.

- [ ] **Step 1: Write failing scope and filtering tests**

```python
def test_search_confirmed_incidents_filters_by_service_environment_and_tenant() -> None:
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_resolved_incident_memory_tools.py -q`

Expected: FAIL because no resolved-incident store exists.

- [ ] **Step 3: Implement a distinct namespace and bounded retrieval**

Add `pinecone_resolved_incidents_namespace` with default `resolved_incidents`; use the existing embedding model and a bounded `top_k`. Require service and environment filters, and include source investigation IDs in returned citations.

- [ ] **Step 4: Verify and commit**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_resolved_incident_memory_tools.py -q`

Commit: `feat: add scoped resolved incident retrieval`

### Task 3: Expose confirmed lessons to the Knowledge specialist

**Files:**
- Modify: `apps/api/src/incidentflow/agent/tools/incident_response_guide_tools.py`
- Modify: `apps/api/src/incidentflow/agent/agents_specialist/knowledge.py`
- Modify: `apps/api/src/incidentflow/agent/prompts/knowledge.py`
- Modify: `apps/api/tests/test_knowledge_agent.py`

**Interfaces:**
- Consumes: `search_confirmed_incidents` from Task 2.
- Produces: Knowledge findings that identify whether evidence came from a runbook or a confirmed historical incident.

- [ ] **Step 1: Write failing specialist-tool selection tests**

```python
def test_knowledge_agent_receives_runbook_and_confirmed_incident_tools() -> None:
    assert {tool.name for tool in build_knowledge_tools()} >= {
        "search_incident_response_guides", "search_confirmed_incidents"
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_knowledge_agent.py -q`

Expected: FAIL because the resolved-incident search tool is not exposed.

- [ ] **Step 3: Add the read-only memory tool without changing runbook retrieval**

Keep `search_incident_response_guides` unchanged. Add the new tool only when Pinecone resolved-incident memory is explicitly enabled; otherwise return no simulated historical incident.

- [ ] **Step 4: Verify and commit**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_knowledge_agent.py tests/test_resolved_incident_memory_tools.py -q`

Commit: `feat: surface confirmed incident lessons to knowledge agent`
