/** Final investigation report: root cause, causal chain, next actions, evidence. */
import { useState } from 'react'
import type { CausalStep, InvestigationEvidence, InvestigationReport } from '../../api'

const SOURCE_NAMES: Record<string, string> = {
  cloudwatch: 'CloudWatch',
  data_intelligence: 'MongoDB events',
  knowledge: 'Knowledge base',
  github: 'GitHub',
  it_operations: 'Jira',
}

/** Words the agents use for each source when they name it in free text. */
const SOURCE_HINTS: Array<[string, RegExp]> = [
  ['data_intelligence', /mongo|operational_events|events_collection/],
  ['it_operations', /jira|ticket/],
  ['knowledge', /pinecone|runbook|similar_incident/],
  ['cloudwatch', /alarm|metric|log_group/],
  ['github', /commit|pull_request|repository/],
]

/** "ask_cloudwatch", "CloudWatch Observability Agent" and "cloudwatch" all name one source. */
export function sourceKey(source: string) {
  const plain = source.toLowerCase().replace(/^ask_/, '').replace(/[\s/-]+/g, '_')
  return Object.keys(SOURCE_NAMES).find((key) => plain.includes(key))
    ?? SOURCE_HINTS.find(([, hint]) => hint.test(plain))?.[0]
    ?? plain
}

export const sourceName = (source: string) => SOURCE_NAMES[sourceKey(source)] ?? source

const VISIBLE_ACTIONS = 3

function ConfidenceMeter({ value }: { value: number }) {
  const percent = Math.round(value * 100)
  const level = percent >= 75 ? 'high' : percent >= 50 ? 'medium' : 'low'
  return (
    <div aria-label={`Confidence ${percent}%`} className={`confidence-meter is-${level}`} role="img">
      <span>Confidence</span>
      <div className="confidence-track"><div style={{ width: `${percent}%` }} /></div>
      <strong>{percent}%</strong>
    </div>
  )
}

/** The chain from first cause to customer symptom; clicking a step shows the evidence behind it. */
function CausalChain({ steps, evidence }: { steps: CausalStep[], evidence: InvestigationEvidence[] }) {
  const [selected, setSelected] = useState(0)
  const step = steps[Math.min(selected, steps.length - 1)]
  const supporting = evidence.filter((item) => sourceKey(item.source) === sourceKey(step.source))

  return (
    <section aria-label="Causal chain" className="causal-chain">
      <h3>How it happened</h3>
      <ol aria-label="Steps" className="causal-steps">
        {steps.map((item, index) => (
          <li className={`${item.verified ? 'is-verified' : 'is-hypothesis'} ${index === selected ? 'is-selected' : ''} ${index === steps.length - 1 ? 'is-symptom' : ''}`.trim()} key={`${item.label}-${index}`}>
            <button aria-pressed={index === selected} onClick={() => setSelected(index)} type="button">
              <small>{index === 0 ? 'Origin' : index === steps.length - 1 ? 'Symptom' : `Step ${index + 1}`}</small>
              <strong>{item.label}</strong>
              <span>{sourceName(item.source)}{item.verified ? '' : ' · hypothesis'}</span>
            </button>
          </li>
        ))}
      </ol>
      <div aria-label="Selected step" aria-live="polite" className="causal-detail" role="region">
        <p>{step.detail}</p>
        <small>{step.verified ? 'Observed by' : 'Suggested by'} {sourceName(step.source)}{step.verified ? '' : ' (not confirmed by evidence)'}</small>
        {supporting.length > 0 && (
          <ul>{supporting.map((item, index) => <li key={index}>{item.detail}</li>)}</ul>
        )}
      </div>
    </section>
  )
}

/**
 * The final report, shortest first: where the problem comes from, how it unfolded, what to do,
 * then the full evidence and limits folded away for whoever wants to check them.
 */
export function ReportDetails({ report }: { report: InvestigationReport }) {
  const [showAllActions, setShowAllActions] = useState(false)
  const evidence = report.evidence ?? []
  const hypotheses = report.hypotheses ?? []
  const actions = report.proposed_actions ?? []
  const limitations = report.limitations ?? []
  const chain = report.causal_chain ?? []
  const shownActions = showAllActions ? actions : actions.slice(0, VISIBLE_ACTIONS)
  const bySource = evidence.reduce<Record<string, InvestigationEvidence[]>>((groups, item) => {
    const key = sourceName(item.source)
    return { ...groups, [key]: [...(groups[key] ?? []), item] }
  }, {})

  return (
    <section aria-label="Investigation report" className="investigation-report">
      <div className="report-heading">
        <div><p>INVESTIGATION REPORT</p><h2>Where the problem comes from</h2></div>
        <ConfidenceMeter value={report.confidence} />
      </div>

      <div className="root-cause">
        <small>{report.root_cause ? 'Root cause' : 'Summary'}</small>
        <strong>{report.root_cause ?? report.summary}</strong>
      </div>

      {chain.length > 0 && <CausalChain evidence={evidence} steps={chain} />}

      {actions.length > 0 && (
        <section aria-label="What to do next" className="report-actions">
          <h3><span aria-hidden="true">✅</span> What to do next</h3>
          <ol>{shownActions.map((item, index) => <li key={index}>{item}</li>)}</ol>
          {actions.length > VISIBLE_ACTIONS && (
            <button className="quiet-button" onClick={() => setShowAllActions((value) => !value)} type="button">
              {showAllActions ? 'Show fewer' : `Show all ${actions.length} actions`}
            </button>
          )}
        </section>
      )}

      <div className="report-more">
        {report.root_cause && (
          <details><summary>Full summary</summary><p>{report.summary}</p></details>
        )}
        <details>
          <summary>Evidence by source <b>{evidence.length}</b></summary>
          {evidence.length === 0 ? <p>No evidence was returned.</p> : Object.entries(bySource).map(([source, items]) => (
            <div className="evidence-source" key={source}>
              <strong>{source}</strong>
              {items.map((item, index) => (
                <p key={index}><span className={`evidence-status is-${item.source_status}`}>{item.source_status}</span>{item.detail}</p>
              ))}
            </div>
          ))}
        </details>
        {(hypotheses.length > 0 || limitations.length > 0) && (
          <details>
            <summary>Hypotheses and limits <b>{hypotheses.length + limitations.length}</b></summary>
            {hypotheses.length > 0 && <><h4>Hypotheses</h4><ul>{hypotheses.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
            {limitations.length > 0 && <><h4>Limits</h4><ul>{limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
          </details>
        )}
      </div>
    </section>
  )
}
