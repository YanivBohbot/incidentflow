# IncidentFlow Promo Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a ~90 s 1080p MP4 (and a ~15 s README GIF) where the real IncidentFlow app,
filmed automatically, carries animated explanations at each step of a live investigation.

**Architecture:** A Playwright script drives the real Docker stack, records the viewport to
WebM, and writes a timeline JSON of what happened when (polled from `/api/investigations/{id}/trace`
and from UI milestones). A pure `buildEdit()` turns that timeline into video segments (cut / speed
up waits). Remotion composes animated intro/outro scenes plus the footage with timeline-driven
callouts and masks, and renders the MP4.

**Tech Stack:** Node 24, TypeScript, Remotion 4 (`remotion`, `@remotion/cli`, `@remotion/media`
or `OffthreadVideo`), Playwright (`@playwright/test` library API, Chromium), Vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-promo-video-design.md`

## Global Constraints

- Everything lives in `incidentflow/promo-video/`; no change to `apps/api` or `apps/web` for the video.
- Output 1920×1080, 30 fps, 16:9, ~90 s; English burned-in text; no voice-over; no music yet.
- Dark, sober theme consistent with the app; nothing flashy.
- 100% real footage: the UI is never mocked or altered; masking (blur) sensitive regions is allowed.
- Never on screen: `.env`, DevTools, tokens, AWS account IDs, the `*.atlassian.net` site name,
  the "Fixed Jira target" block of the review panel.
- Only true claims; numbers shown must be measured from the take (e.g. real duration) or dropped.
- Hook copy (owner-approved): "3 AM. refund-service is throwing 5xx errors. Here's how IncidentFlow investigates."
  A later caption states that scenarios are realistic simulations.
- End card: "Yaniv Bohbot" · `github.com/YanivBohbot`; repo URL slot added once published.
- At most 3 live takes. The script plays the operator: types an approval note at human speed,
  then clicks "Approve and resume".
- Stack must run with `-f docker-compose.yml -f docker-compose.cloudwatch.yml`, MongoDB MCP on
  `127.0.0.1:3000`, and CloudWatch data re-seeded right before the take.
- `footage/` and `out/` are git-ignored (raw takes may contain sensitive frames).

## Review Focus

1. Investigation finishes `COMPLETED` without pausing (existing SAM1 ticket) → script must stop
   with a clear "no HITL pause — delete the scenario's SAM1 tickets" error, not film a useless take.
2. Investigation `FAILED` or exceeds 5 min → script aborts, keeps nothing as a "good" take.
3. Trace steps arrive in bursts (polling every ~1 s) → timeline times are first-seen times;
   `buildEdit` must stay monotonic and never produce negative or overlapping segments.
4. A sub-agent never appears in the trace (integration down) → its callout is simply not shown;
   no callout may claim a step that did not happen.
5. Mask regions come from DOM bounding boxes captured during filming → if an element is absent,
   no mask is emitted and the frame check (Task 6) must still be passed by a human-visible review.

---

### Task 1: Scaffold the Remotion + Playwright project

**Files:**
- Create: `promo-video/package.json`, `promo-video/tsconfig.json`, `promo-video/remotion.config.ts`,
  `promo-video/src/index.ts`, `promo-video/src/Root.tsx`, `promo-video/src/theme.ts`,
  `promo-video/.gitignore` (`node_modules/`, `footage/`, `out/`), `promo-video/README.md`
- Test: `promo-video/src/theme.test.ts`

**Interfaces:**
- Produces: composition id `IncidentFlowPromo` (1920×1080, 30 fps); `theme` object
  `{ bg: '#0d1117', panel: '#161b22', border: '#30363d', text: '#e6edf3', dim: '#8b949e',
  accent: '#58a6ff', ok: '#3fb950', warn: '#d29922', danger: '#ff7b72', font: 'Inter, system-ui' }`;
  npm scripts `film`, `studio`, `render`, `gif`, `test`.

- [ ] Step 1: `npm init` + install `remotion @remotion/cli react react-dom playwright typescript tsx vitest`; `npx playwright install chromium`.
- [ ] Step 2: Test `theme.test.ts`: `expect(theme.bg).toBe('#0d1117')` and every color matches `/^#[0-9a-f]{6}$/`. Run `npx vitest run` → FAIL (no module).
- [ ] Step 3: Implement `theme.ts`, `Root.tsx` registering `IncidentFlowPromo` with a placeholder black composition of 90 s (2700 frames).
- [ ] Step 4: `npx vitest run` → PASS; `npx remotion compositions src/index.ts` lists `IncidentFlowPromo`.
- [ ] Step 5: Commit `Add promo video project scaffold`.

### Task 2: Timeline model and edit decisions

**Files:**
- Create: `promo-video/src/timeline/types.ts`, `promo-video/src/timeline/buildEdit.ts`
- Test: `promo-video/src/timeline/buildEdit.test.ts`

**Interfaces:**
- Produces:
  - `type TimelineEvent = { t: number /* s since recording start */; kind: 'page' | 'click' |
    'trace_step' | 'hitl_pause' | 'typing_start' | 'typing_end' | 'approved' | 'completed';
    label: string; agent?: string /* e.g. 'ask_github' */; tool?: string; box?: Box }`
  - `type Box = { x: number; y: number; width: number; height: number }` (viewport px)
  - `type Timeline = { recording: string; durationS: number; investigationId: string;
    events: TimelineEvent[]; masks: { from: number; to: number; box: Box }[] }`
  - `type Segment = { srcFrom: number; srcTo: number; speed: number }` (seconds in source)
  - `buildEdit(timeline: Timeline, opts?: { maxIdleS?: number /* 2.5 */; waitSpeed?: number /* 4 */ }): Segment[]`
  - `srcToOutFrame(segments: Segment[], srcT: number, fps: number): number | null`

- [ ] Step 1: Tests:
  - `test_idle_gaps_longer_than_maxIdle_are_sped_up`: events at t=0,1,20,21 → a segment covering 1→20 with `speed === 4`, others `speed === 1`.
  - `test_typing_and_hitl_are_never_sped_up`: span typing_start→typing_end has `speed === 1`.
  - `test_segments_are_contiguous_and_monotonic`: for every i, `segments[i].srcTo === segments[i+1].srcFrom` and `srcFrom < srcTo`, first `srcFrom === 0`, last `srcTo === durationS`.
  - `test_unsorted_or_duplicate_event_times_are_tolerated` (Review Focus 3).
  - `test_srcToOutFrame_maps_through_speedups`: t=20 with the first case → frame `(1 + 19/4) * 30`.
- [ ] Step 2: `npx vitest run src/timeline` → FAIL.
- [ ] Step 3: Implement (sort + dedupe events; walk gaps; protected spans = typing and ±1.5 s around `hitl_pause`/`approved`).
- [ ] Step 4: `npx vitest run` → PASS.
- [ ] Step 5: Commit `Add timeline edit decisions for promo video`.

### Task 3: Automated filming script

**Files:**
- Create: `promo-video/film/preflight.ts`, `promo-video/film/film.ts`, `promo-video/film/traceWatcher.ts`
- Test: `promo-video/film/traceWatcher.test.ts`

**Interfaces:**
- Consumes: `Timeline`, `TimelineEvent` (Task 2). API: `GET http://127.0.0.1:8000/api/investigations`,
  `GET /api/investigations/{id}/trace` (steps `{kind, actor, title, status, confidence, data:{tool?}}`),
  `GET /health/ready`. Web app at `http://127.0.0.1:5174`.
- Produces: `npm run film -- --take N [--rehearse]` → `footage/take-N.webm` + `footage/take-N.timeline.json`.
  `diffTraceSteps(prev: TraceStep[], next: TraceStep[], t: number): TimelineEvent[]`.

- [ ] Step 1: Test `traceWatcher.test.ts`: `diffTraceSteps([], [delegation(ask_github)], 12)` → one `trace_step` with `agent: 'ask_github'`, `t: 12`; calling again with the same list → `[]`; a `review` step → `hitl_pause`.
- [ ] Step 2: `npx vitest run film` → FAIL. Step 3: implement `traceWatcher.ts`. Step 4: PASS.
- [ ] Step 5: `preflight.ts` checks, each failing with a one-line fix hint: `/health/ready` OK; `127.0.0.1:3000/mcp` answers (any HTTP code); `docker inspect incidentflow-api-1` shows the `.aws` mount; web reachable. (CloudWatch re-seed is run by the operator command in README, not by the script.)
- [ ] Step 6: `film.ts` (Chromium headless, viewport 1920×1080, `recordVideo` same size, `deviceScaleFactor: 1`): Overview (hold 3 s) → Incidents → click the `<strong>` "[Demo] Refund requests failing (refund-service)" → hold 2 s → "Launch multi-agent investigation" → auto-navigates to Investigations; poll `/trace` every 1 s, append events, scroll the trace list into view → on lifecycle `AWAITING_HUMAN_REVIEW` (UI goes to Approvals) record `hitl_pause`, capture bounding boxes of `[aria-label="Fixed Jira target"]` and any element whose text matches `/atlassian\.net|\d{12}/` into `masks` (from now to end) → `typing_start`, type `Verified against CloudWatch, GitHub PR #7 and the runbook. Approved — create the SAM1 task.` into the "Reason or question…" textarea with `delay: 45` → `typing_end` → click "Approve and resume" → `approved` → go to Investigations, open the investigation, wait for `COMPLETED` → `completed`, hold 4 s, close context (flushes video), write timeline JSON.
- [ ] Step 7: Abort rules (Review Focus 1–2): lifecycle `COMPLETED` with no `review` step → exit 2 "no HITL pause — delete this scenario's SAM1 tickets"; `FAILED` or >300 s → exit 3. `--rehearse` stops before clicking Launch (no LLM cost).
- [ ] Step 8: Run `npm run film -- --take 0 --rehearse` → WebM exists and plays; timeline has `page`/`click` events.
- [ ] Step 9: Commit `Add automated filming script for promo video`.

### Task 4: Animated scenes (hook, problem, recap, end card)

**Files:**
- Create: `promo-video/src/scenes/Hook.tsx`, `Problem.tsx`, `Recap.tsx`, `EndCard.tsx`,
  `promo-video/src/content/architecture.ts`
- Test: `promo-video/src/content/architecture.test.ts`

**Interfaces:**
- Produces: `architecture = { supervisor: 'Investigation Supervisor (LangGraph)', agents: AgentInfo[] }`
  with `AgentInfo = { tool: string; name: string; source: string; middleware: string[] }`:
  - `ask_cloudwatch` · CloudWatch Observability Agent · AWS CloudWatch MCP (awslabs) · `CloudWatchReadOnlyPolicyMiddleware`
  - `ask_github` · GitHub Agent · GitHub MCP (HTTP) · `GitHubRepositoryAllowlistMiddleware`, `ToolCallLimitMiddleware`
  - `ask_data_intelligence` · Data Intelligence Agent · MongoDB MCP · `TruncateToolOutputMiddleware`
  - `ask_knowledge` · Knowledge Agent · Pinecone (runbooks) · read-only retrieval
  - `ask_it_operations` · IT Operations Agent · Atlassian MCP (Jira) · `HumanInTheLoopMiddleware`
  - shared on every agent: `ExternalEvidenceBoundaryMiddleware`; supervisor: `LLMToolSelectorMiddleware`, `ToolRetryMiddleware`, `ToolCallLimitMiddleware`, `ModelCallLimitMiddleware`.
  Each scene: `({ durationInFrames }: { durationInFrames: number }) => JSX`.

- [ ] Step 1: Test: every `architecture` string ending in `Middleware` appears in `../apps/api/src` (read files with `fs`, `grep`-style) — guards "only true claims". Run → FAIL.
- [ ] Step 2: Implement `architecture.ts` → PASS. Re-verify each name against the API source before writing.
- [ ] Step 3: Scenes: Hook 6 s (hook copy, red pulsing alert line), Problem 9 s (six tool chips stacking: CloudWatch logs, Alarms, GitHub commits, MongoDB events, Runbooks, Jira + "Context is scattered across tools"), Recap 8 s (full diagram supervisor → 5 agents → sources, middleware band; stack chips LangGraph · LangChain create_agent · MCP · FastAPI · React · PostgreSQL · Docker; caption "Scenarios are realistic simulations on real integrations."), EndCard 5 s.
- [ ] Step 4: Check each in `npm run studio` (stills: `npx remotion still src/index.ts IncidentFlowPromo out/hook.png --frame=60`).
- [ ] Step 5: Commit `Add animated scenes for promo video`.

### Task 5: Demo scene with timeline-driven callouts and masks

**Files:**
- Create: `promo-video/src/scenes/Demo.tsx`, `promo-video/src/components/WindowFrame.tsx`,
  `Callout.tsx`, `Mask.tsx`, `promo-video/src/content/callouts.ts`
- Modify: `promo-video/src/Root.tsx` (sequence Hook → Problem → Demo → Recap → EndCard; total frames
  computed from `buildEdit` via `calculateMetadata`; footage path from `public/take.webm` + `public/take.timeline.json`)
- Test: `promo-video/src/content/callouts.test.ts`

**Interfaces:**
- Consumes: `Timeline`, `buildEdit`, `srcToOutFrame` (Task 2), `architecture` (Task 4).
- Produces: `calloutsFor(timeline: Timeline): { atSrc: number; holdS: number; title: string; body: string; chips: string[] }[]`
  — dashboard callout "Realistic, seeded incident scenarios" at first Incidents `page` event; launch
  callout "Supervisor (LangGraph) delegates to sub-agents as tools" at the launch `click`; one per
  first `trace_step` of each agent (title = agent name, chips = source + middleware); HITL callout
  "HumanInTheLoopMiddleware pauses before createJiraIssue" at `hitl_pause`; "Atlassian MCP created the
  ticket" at `completed`; a measured caption "Investigation to approval request: {X} s" where X =
  `hitl_pause.t − launch click.t`, rounded.

- [ ] Step 1: Tests: agent with no `trace_step` → no callout for it (Review Focus 4); measured caption uses the timeline numbers; callouts sorted by `atSrc`.
- [ ] Step 2: Run → FAIL. Step 3: implement `callouts.ts` → PASS.
- [ ] Step 4: `Demo.tsx`: one `<Sequence>` per `Segment` with `<OffthreadVideo startFrom endAt playbackRate={speed}>`; `WindowFrame` draws a neutral title bar "IncidentFlow" (no URL); `Callout` slides in at `srcToOutFrame(atSrc)`; `Mask` blurs `timeline.masks` boxes (scaled to the frame); "×4" badge while `speed > 1`.
- [ ] Step 5: Copy the rehearsal take into `public/`, preview in studio, adjust callout placement so it never covers the highlighted trace line.
- [ ] Step 6: Commit `Add demo scene with callouts and masks`.

### Task 6: Live take, render, GIF, frame check

**Files:**
- Modify: `promo-video/README.md` (exact operator runbook below)

- [ ] Step 1: Operator runbook in README: start stack with the CloudWatch override; start MongoDB MCP (`npx -y mongodb-mcp-server@latest --transport http --httpHost 127.0.0.1 --httpPort 3000 --readOnly`, connection string from `apps/api/.env`); `python scripts/seed_cloudwatch_scenarios.py --profile default`; wait 3 min; delete the scenario's SAM1 tickets.
- [ ] Step 2: `npm run film -- --take 1` → exit 0, timeline contains `hitl_pause`, `approved`, `completed` and a `trace_step` for each of the 5 agents. Otherwise fix the cause; ≤3 takes total.
- [ ] Step 3: Copy the take into `public/`; `npm run render` → `out/incidentflow-promo.mp4`, 1920×1080, 80–100 s (`ffprobe`).
- [ ] Step 4: Frame check: export 1 still per second of the Demo (`npx remotion still … --frame=N` loop or ffmpeg `fps=1`) and inspect every image for account IDs, `atlassian.net`, tokens, `.env`. Any hit → add a mask, re-render.
- [ ] Step 5: `npm run gif` → `out/incidentflow-loop.gif` (~15 s: trace lighting up → HITL approve), < 10 MB.
- [ ] Step 6: Commit `Add promo video runbook` (no footage, no output).
