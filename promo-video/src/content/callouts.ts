import type { Timeline } from '../timeline/types'
import { agentByTool, architecture } from './architecture'

export type Callout = {
  /** Source-recording time at which the callout appears. */
  atSrc: number
  /** How long it stays, in output seconds. */
  holdS: number
  title: string
  body: string
  chips: string[]
  tone?: 'accent' | 'warn' | 'ok'
}

/** The explanations shown next to the real app, each tied to something that happened in the take. */
export function calloutsFor(timeline: Timeline): Callout[] {
  const events = [...timeline.events].sort((a, b) => a.t - b.t)
  const callouts: Callout[] = []

  const incidents = events.find((e) => e.kind === 'page' && e.label === 'Incidents')
  if (incidents) {
    callouts.push({
      atSrc: incidents.t,
      holdS: 5,
      title: 'Realistic incident scenarios',
      body: 'Seeded demo incidents backed by real CloudWatch alarms, MongoDB events, GitHub PRs and runbooks.',
      chips: [],
    })
  }

  const launch = events.find((e) => e.kind === 'click' && e.label === 'Launch investigation')
  if (launch) {
    callouts.push({
      atSrc: launch.t,
      holdS: 5,
      title: `${architecture.supervisor} takes over`,
      body: 'A LangGraph workflow runs a create_agent supervisor that calls specialist sub-agents as tools.',
      chips: architecture.supervisorMiddleware,
    })
  }

  const seenAgents = new Set<string>()
  for (const event of events) {
    if (event.kind !== 'trace_step' || !event.agent || seenAgents.has(event.agent)) continue
    const agent = agentByTool(event.agent)
    if (!agent) continue
    seenAgents.add(event.agent)
    callouts.push({
      atSrc: event.t,
      holdS: 6,
      title: agent.name,
      body: `Called by the supervisor as the tool ${agent.tool}.`,
      chips: [agent.source, ...agent.middleware],
    })
  }

  const pause = events.find((e) => e.kind === 'hitl_pause')
  if (pause) {
    callouts.push({
      atSrc: pause.t,
      holdS: 7,
      title: 'Human in the loop',
      body: 'HumanInTheLoopMiddleware stops the Jira agent before createJiraIssue. Nothing is written until an operator approves.',
      chips: ['HumanInTheLoopMiddleware', 'LangGraph interrupt()'],
      tone: 'warn',
    })
    if (launch) {
      callouts.push({
        atSrc: pause.t,
        holdS: 7,
        title: 'Measured on this take',
        body: `Launch → approval request: ${Math.round(pause.t - launch.t)} s`,
        chips: [],
      })
    }
  }

  const completed = events.find((e) => e.kind === 'completed')
  if (completed && pause) {
    callouts.push({
      atSrc: completed.t,
      holdS: 5,
      title: 'Approved → ticket created',
      body: 'The workflow resumed from its PostgreSQL checkpoint and the Jira agent created the task through Atlassian MCP.',
      chips: ['Command(resume=…)', 'Atlassian MCP'],
      tone: 'ok',
    })
  }

  return callouts.sort((a, b) => a.atSrc - b.atSrc)
}
