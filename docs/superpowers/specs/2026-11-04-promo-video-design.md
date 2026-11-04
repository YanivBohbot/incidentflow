# IncidentFlow promo video — design

Date: 2026-11-04
Status: draft, owner questions answered — awaiting final approval

## Intent

A ~90-second video that presents IncidentFlow to **recruiters and technical teams**. It is a
showcase of the author's engineering skill through a real, working multi-agent system — not a
marketing product promo. It will be posted on GitHub (README) and social networks (LinkedIn, X,
possibly YouTube).

Two audiences must be served at once:

- **Recruiter (often non-technical)**: watches ~20–30 s. Must leave with: "this person built a
  real, end-to-end AI multi-agent system that works."
- **Technical reviewer**: watches to the end and looks for signs of rigour: clear architecture,
  agents-as-tools orchestration, MCP integrations, middleware/guardrails, human-in-the-loop.

## What the owner explicitly wants shown

1. The **HITL flow** together with the **live agent trace** (the highlight).
2. That there are **several agents**, orchestrated with the **Agents-as-Tools pattern** using
   **LangGraph / LangChain** (supervisor calling `create_agent` sub-agents as tools).
3. **Integration with several MCP servers**.
4. The **middleware** layer.
5. The **frontend dashboard** with **realistic incident scenarios**.

## Core format decision (owner-validated)

The backbone of the video is **the real application, recorded**. Explanations are **animated
overlays on top of the real footage, appearing at the moment the corresponding step happens**
(callouts, highlights, small diagrams). The full architecture diagram is *not* front-loaded: it
builds up progressively during the demo and appears complete as a recap at the end.

The demo must be **100% real end to end** (owner decision): no faked UI, no replaced takes from
earlier runs. Broken integrations are fixed before filming (see Prerequisites).

## Structure (~90 s, 16:9)

| # | Segment | Source | Content / overlay |
|---|---------|--------|-------------------|
| 0 | Hook (0–6 s) | animated | Framed as a reenactment (owner-approved): "3 AM. refund-service is throwing 5xx errors. Here's how IncidentFlow investigates." Later on screen, state clearly that scenarios are realistic simulations. |
| 1 | Problem (6–15 s) | animated | Context scattered across tools (logs, alarms, commits, events, runbooks, Jira); time lost before first hypothesis |
| 2 | Dashboard | real app | Incident list with seeded realistic scenarios → callout "real-world seeded scenarios" |
| 3 | Launch | real app | Click *Investigate* on refund-service (High) → mini-diagram "Supervisor (LangGraph)" overlay |
| 4 | Agent trace | real app, sped up | Each sub-agent call lights up in the trace → callout naming the sub-agent, its MCP server/data source and its middleware (e.g. GitHub sub-agent · GitHub MCP over HTTP · `GitHubRepositoryAllowlistMiddleware`) |
| 5 | HITL | real app | Pause before `createJiraIssue` → callout `HumanInTheLoopMiddleware` → operator clicks Approve |
| 6 | Jira | real app | Ticket created → callout "Atlassian MCP" (optionally a short shot of the real Jira ticket) |
| 7 | Recap + stack | animated | Complete architecture diagram; stack (LangGraph, LangChain `create_agent`, MCP, FastAPI, React, PostgreSQL, Docker, test count) |
| 8 | End card | animated | "Yaniv Bohbot" + github.com/YanivBohbot (owner-approved); repo link added once published |

Timings of segments 2–6 come from the real recording (see "Sync") and are compressed in the edit.

### Architecture facts to show (from the codebase, to be re-verified at build time)

- Supervisor orchestrator (LangGraph) calling sub-agents as tools: `ask_cloudwatch`,
  `ask_github`, data intelligence (MongoDB), `ask_knowledge` (Pinecone runbooks), IT operations
  (Jira). Sub-agents live in `apps/api/src/incidentflow/agent/agents_specialist/`.
- MCP: CloudWatch MCP (awslabs), GitHub MCP (HTTP transport), MongoDB MCP, Atlassian MCP.
  Pinecone for knowledge retrieval.
- Middleware actually used: `HumanInTheLoopMiddleware`, `CloudWatchReadOnlyPolicyMiddleware`,
  `GitHubRepositoryAllowlistMiddleware`, `ExternalEvidenceBoundaryMiddleware`,
  `ToolCallLimitMiddleware`, `ModelCallLimitMiddleware`, `ToolRetryMiddleware`,
  `LLMToolSelectorMiddleware`, `TruncateToolOutputMiddleware`.

Only claims that are true in the code may appear on screen. Numbers such as "45 min → 3 min"
are placeholders; any figure shown must be measured (e.g. the real investigation duration from
the recording) or dropped.

## How it gets made

Decided with the owner:

- **Remotion** (React/TypeScript) for composition and rendering — chosen over HyperFrames for
  maturity and fit with the existing React frontend.
- **Automated filming**: the builder launches the stack and drives the app with a script; the
  owner does not record anything by hand.

Builder's calls (owner may override):

- Location: `incidentflow/promo-video/` — self-contained Node project (Remotion + Playwright),
  no changes to the API or web app code for the video's sake.
- Filming: Playwright, Chromium, 1920×1080 viewport, `recordVideo`, against the Docker stack
  (`http://127.0.0.1:5173`). Scenario: `refund-service` (High). The script performs the real
  clicks, including *Approve* at the HITL pause. Owner decision: the script plays the operator —
  it types a visible approval note in the review panel (typed at human speed so it reads on
  screen) and clicks *Approve*.
- The incident list is filmed as-is, including older test incidents (owner: it looks more real).
- **Sync**: while filming, the script writes a timeline JSON (e.g. `{event: "subagent_start",
  name: "ask_github", t: 41.2}`, HITL pause, approve, Jira created) by observing the DOM and/or
  polling `GET /api/investigations/{id}/trace`. Remotion reads this JSON to place overlays and to
  cut/speed-up waiting periods automatically.
- Browser chrome is not recorded (headless viewport only); Remotion draws a clean window frame.
- Language: English on-screen text, burned in (videos autoplay muted). No voice-over.
- Music: royalty-free track picked by the owner; none until then.
- Visual tone: sober, technical, dark theme consistent with the app.
- Outputs: `out/incidentflow-promo.mp4` (1080p, 16:9, ~90 s) and a ~15 s GIF/MP4 loop for the
  top of the README.
- End card: "Yaniv Bohbot", github.com/YanivBohbot; the repo URL is added once published.

## Constraints and anti-goals

- **No secrets on screen, ever**: no `.env`, DevTools, tokens, AWS account IDs, internal URLs.
  Only seeded demo data. Raw recordings are reviewed (frame check) before rendering.
- Not fake: no mocked UI, no hand-made screenshots passed off as the app.
- Not a 10-minute code walkthrough (possible later, separate video).
- Not flashy marketing; nothing that would look embarrassing to a senior engineer.
- Every filming run costs real LLM calls: keep the number of takes small.

## Prerequisites (separate work items, in this order, before filming)

1. **Purge the OpenAI key from git history** (local commit `790f2fe`, `apps/api/.env.example`):
   owner revokes the key; builder backs up the repo and rewrites unpushed history with
   `git filter-repo` (key → `CHANGE_ME`) after explicit owner go-ahead; verify no occurrence
   remains. Required before anything is pushed to GitHub.
2. **Fix the GitHub sub-agent** (it stops before writing its finding) — root-cause first, then
   validate live.
3. **Fix Jira** (expired OAuth token; owner likely has to re-login interactively via
   `verify_jira_read_access.py`), then validate the full HITL → Jira ticket path live.

## Builder's calls after review (owner may override)

- **Prerequisites are not part of the video plan.** They are done first as separate work items.
  The video plan may build the Remotion project and the filming script in parallel against a
  rehearsal recording, but the final take happens only after prerequisites 1–3 are done.
- **Masking sensitive spans is allowed** and is not "faking": Remotion blurs/crops regions listed
  in the timeline (AWS account IDs in log-group ARNs, the `*.atlassian.net` site name, Jira
  target site in the HITL panel). The Jira site name counts as sensitive. The UI itself is never
  altered. A frame check of the final render is still mandatory.
- **Take budget**: rehearse the script against a local fixture/rehearsal run first; at most 3
  live takes. Re-run `seed_cloudwatch_scenarios.py` right before filming so data is fresh, and
  start the stack with `docker-compose.cloudwatch.yml` plus the MongoDB MCP server (port 3000).
  Jira tickets are not deleted by default (owner). Note: the Jira agent skips creation when a
  SAM1 ticket for the same service was updated in the last 7 days, so the filmed scenario must
  have no such ticket at take time or the HITL pause will not happen.
- If the run also hits the report-level review pause, the script approves it and the edit cuts it.

## Left to the builder

Overlay visual design details, exact easing/transitions, font choice, speed-up factors, GIF
segment choice, and the internal structure of the Remotion project.
