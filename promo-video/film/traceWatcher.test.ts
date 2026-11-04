import { describe, expect, it } from 'vitest'
import { diffTraceSteps, type TraceStep } from './traceWatcher'

const step = (kind: string, actor: string, title: string, tool?: string): TraceStep => ({
  kind,
  actor,
  title,
  status: 'info',
  confidence: null,
  data: tool ? { tool } : {},
})
const delegation = step('delegation', 'Investigation Supervisor', 'Delegated to GitHub Agent', 'ask_github')

describe('diffTraceSteps', () => {
  it('emits one trace_step per new step with its agent and time', () => {
    const events = diffTraceSteps([], [delegation], 12)
    expect(events).toEqual([
      { t: 12, kind: 'trace_step', stepKind: 'delegation', label: 'Delegated to GitHub Agent', agent: 'ask_github' },
    ])
  })

  it('emits nothing for steps already seen', () => {
    expect(diffTraceSteps([delegation], [delegation], 13)).toEqual([])
  })

  it('maps a sub-agent call to its agent tool and called tool', () => {
    const call = step('subagent_call', 'GitHub Agent', 'Called list_pull_requests')
    const [event] = diffTraceSteps([delegation], [delegation, call], 20)
    expect(event).toMatchObject({ agent: 'ask_github', tool: 'list_pull_requests', stepKind: 'subagent_call' })
  })

  it('turns a review pause into hitl_pause', () => {
    const pause = step('review_pause', 'Human-in-the-loop middleware', 'Paused before createJiraIssue')
    expect(diffTraceSteps([], [pause], 40)[0].kind).toBe('hitl_pause')
  })

  it('counts repeated identical steps separately', () => {
    const call = step('subagent_call', 'Knowledge Agent', 'Called search_incident_response_guides')
    expect(diffTraceSteps([call], [call, call], 30)).toHaveLength(1)
  })
})
