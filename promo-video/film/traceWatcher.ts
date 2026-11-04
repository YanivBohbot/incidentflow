import type { TimelineEvent } from '../src/timeline/types'

/** One step of `GET /api/investigations/{id}/trace`. */
export type TraceStep = {
  kind: string
  actor: string
  title: string
  status: string
  confidence: number | null
  detail?: string | null
  data?: { tool?: string; [key: string]: unknown }
}

/** Trace actor name → supervisor delegation tool. */
export const AGENT_TOOLS: Record<string, string> = {
  'CloudWatch Observability Agent': 'ask_cloudwatch',
  'Data Intelligence Agent': 'ask_data_intelligence',
  'GitHub Agent': 'ask_github',
  'Knowledge Agent': 'ask_knowledge',
  'IT Operations Agent': 'ask_it_operations',
}

const signature = (s: TraceStep) => `${s.kind}|${s.actor}|${s.title}`

/**
 * Timeline events for the steps in `next` that were not in `prev`, stamped `t`. The trace is
 * rebuilt on every request, so steps are matched by signature with repeat counts, not index.
 */
export function diffTraceSteps(prev: TraceStep[], next: TraceStep[], t: number): TimelineEvent[] {
  const seen = new Map<string, number>()
  for (const s of prev) seen.set(signature(s), (seen.get(signature(s)) ?? 0) + 1)

  const events: TimelineEvent[] = []
  for (const s of next) {
    const key = signature(s)
    const remaining = seen.get(key) ?? 0
    if (remaining > 0) {
      seen.set(key, remaining - 1)
      continue
    }
    if (s.kind === 'review_pause') {
      events.push({ t, kind: 'hitl_pause', label: s.title })
      continue
    }
    const event: TimelineEvent = { t, kind: 'trace_step', stepKind: s.kind, label: s.title }
    const agent = s.data?.tool ?? AGENT_TOOLS[s.actor]
    if (agent) event.agent = agent
    if (s.kind === 'subagent_call') event.tool = s.title.replace(/^Called /, '')
    events.push(event)
  }
  return events
}
