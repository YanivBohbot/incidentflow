import { describe, expect, it } from 'vitest'
import type { Timeline, TimelineEvent } from '../timeline/types'
import { calloutsFor } from './callouts'

const ev = (t: number, kind: TimelineEvent['kind'], label: string, extra: Partial<TimelineEvent> = {}) =>
  ({ t, kind, label, ...extra }) as TimelineEvent

const timeline = (events: TimelineEvent[]): Timeline => ({
  recording: 'take.webm',
  durationS: 200,
  investigationId: 'x',
  events,
  masks: [],
})

const base = [
  ev(4, 'page', 'Incidents'),
  ev(9, 'click', 'Launch investigation'),
  ev(15, 'trace_step', 'Delegated to GitHub Agent', { agent: 'ask_github', stepKind: 'delegation' }),
  ev(14, 'trace_step', 'Delegated to Knowledge Agent', { agent: 'ask_knowledge', stepKind: 'delegation' }),
  ev(30, 'trace_step', 'Called list_commits', { agent: 'ask_github', stepKind: 'subagent_call', tool: 'list_commits' }),
  ev(52.4, 'hitl_pause', 'Paused before createJiraIssue'),
  ev(80, 'completed', 'Investigation completed'),
]

describe('calloutsFor', () => {
  it('shows one callout per agent that actually ran, and none for agents that did not', () => {
    const titles = calloutsFor(timeline(base)).map((c) => c.title)
    expect(titles).toContain('GitHub Agent')
    expect(titles).toContain('Knowledge Agent')
    expect(titles).not.toContain('CloudWatch Observability Agent')
    expect(titles.filter((t) => t === 'GitHub Agent')).toHaveLength(1)
  })

  it('names the agent source and middleware as chips', () => {
    const github = calloutsFor(timeline(base)).find((c) => c.title === 'GitHub Agent')!
    expect(github.chips).toEqual(expect.arrayContaining(['GitHub MCP (HTTP)', 'GitHubRepositoryAllowlistMiddleware']))
  })

  it('states the measured launch-to-approval time from the take', () => {
    const measured = calloutsFor(timeline(base)).find((c) => c.title.startsWith('Measured'))!
    expect(measured.body).toBe('Launch → approval request: 43 s')
    expect(measured.atSrc).toBe(52.4)
  })

  it('omits the measured callout when the take had no HITL pause', () => {
    const titles = calloutsFor(timeline(base.filter((e) => e.kind !== 'hitl_pause'))).map((c) => c.title)
    expect(titles.some((t) => t.startsWith('Measured'))).toBe(false)
  })

  it('returns callouts sorted by source time', () => {
    const times = calloutsFor(timeline(base)).map((c) => c.atSrc)
    expect(times).toEqual([...times].sort((a, b) => a - b))
  })
})
