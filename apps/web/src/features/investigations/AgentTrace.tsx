import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Investigation, TraceStep } from '../../api'

type AgentTraceProps = {
  investigation: Investigation
  /** Hide the heading when the trace is embedded in another card. */
  compact?: boolean
}

const KIND_ICONS: Record<TraceStep['kind'], string> = {
  request: '👤',
  reasoning: '💭',
  delegation: '🧭',
  subagent_call: '🛠',
  finding: '🔎',
  limit: '⛔',
  review_pause: '⏸',
  review_decision: '✋',
  report: '📋',
}

const STATUS_LABELS: Partial<Record<TraceStep['status'], string>> = {
  live: 'Live data',
  unavailable: 'Unavailable',
  pending: 'Waiting for you',
  approved: 'Approved',
  rejected: 'Rejected',
}

const POLL_INTERVAL_MS = 2000

function StepData({ step }: { step: TraceStep }) {
  const evidence = Array.isArray(step.data.evidence) ? step.data.evidence as Array<Record<string, string>> : []
  const hypotheses = Array.isArray(step.data.hypotheses) ? (step.data.hypotheses as unknown[]).filter(Boolean) as string[] : []
  const args = step.data.arguments && typeof step.data.arguments === 'object' ? Object.entries(step.data.arguments as Record<string, unknown>) : []
  const edited = step.data.edited_fields && typeof step.data.edited_fields === 'object' ? Object.entries(step.data.edited_fields as Record<string, string>) : []
  const agents = Array.isArray(step.data.agents_consulted) ? step.data.agents_consulted as string[] : []
  if (!evidence.length && !hypotheses.length && !args.length && !edited.length && !agents.length) return null

  return (
    <details className="trace-data">
      <summary>Details</summary>
      {args.length > 0 && <dl>{args.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{typeof value === 'string' ? value || '—' : JSON.stringify(value)}</dd></div>)}</dl>}
      {edited.length > 0 && <dl>{edited.map(([name, value]) => <div key={name}><dt>edited {name}</dt><dd>{value}</dd></div>)}</dl>}
      {evidence.length > 0 && <ul>{evidence.map((item, index) => <li key={index}><strong>{item.source}</strong> <em>{item.status}</em> — {item.detail}</li>)}</ul>}
      {hypotheses.length > 0 && <p><strong>Hypotheses:</strong> {hypotheses.join(' · ')}</p>}
      {agents.length > 0 && <p><strong>Agents consulted:</strong> {agents.join(', ')}</p>}
    </details>
  )
}

/**
 * Timeline of one investigation: the request, every supervisor delegation, each specialist
 * finding, human-in-the-loop pauses and decisions, then the final report. It refreshes while
 * the investigation is running so the operator can watch the agents work.
 */
export function AgentTrace({ investigation, compact = false }: AgentTraceProps) {
  const [steps, setSteps] = useState<TraceStep[]>([])
  const [error, setError] = useState<string | null>(null)
  const isRunning = investigation.lifecycle === 'RUNNING'

  useEffect(() => {
    let isCurrent = true
    async function load() {
      try {
        const trace = await api.getInvestigationTrace(investigation.id)
        if (isCurrent) { setSteps(trace); setError(null) }
      } catch (caught) {
        if (isCurrent) setError(caught instanceof Error ? caught.message : 'Could not load the agent trace.')
      }
    }
    void load()
    const timer = isRunning ? window.setInterval(() => void load(), POLL_INTERVAL_MS) : undefined
    return () => { isCurrent = false; if (timer) window.clearInterval(timer) }
  }, [investigation.id, investigation.updated_at, isRunning])

  return (
    <section className={`agent-trace ${compact ? 'is-compact' : ''}`} aria-label="Agent trace">
      {!compact && (
        <div className="section-heading">
          <p>MULTI-AGENT TRACE</p>
          <h2>How the agents reached this result</h2>
          <span>Rebuilt from the durable LangGraph checkpoint: each delegation the supervisor chose, what each specialist returned, and every human decision.</span>
        </div>
      )}
      {error && <p className="proposal-error" role="alert">{error}</p>}
      {steps.length === 0 && !error && <p className="muted-copy">{isRunning ? 'The supervisor is starting…' : 'No agent activity recorded for this investigation.'}</p>}
      <ol className="trace-list">
        {steps.map((step, index) => (
          <li className={`trace-step trace-${step.kind} trace-status-${step.status}`} key={index}>
            <span aria-hidden="true" className="trace-icon">{KIND_ICONS[step.kind]}</span>
            <div className="trace-body">
              <div className="trace-heading">
                <small>{step.actor}</small>
                {STATUS_LABELS[step.status] && <span className="trace-badge">{STATUS_LABELS[step.status]}</span>}
                {step.confidence !== null && <span className="trace-badge trace-confidence">{Math.round(step.confidence * 100)}%</span>}
              </div>
              <strong>{step.title}</strong>
              {step.detail && <p>{step.detail}</p>}
              <StepData step={step} />
            </div>
          </li>
        ))}
        {isRunning && <li className="trace-step trace-running"><span aria-hidden="true" className="trace-icon trace-spinner" /><div className="trace-body"><strong>Agents are working…</strong></div></li>}
      </ol>
    </section>
  )
}
