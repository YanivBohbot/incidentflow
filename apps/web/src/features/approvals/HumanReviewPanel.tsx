import { useState } from 'react'
import { AgentTrace } from '../investigations/AgentTrace'
import type { HumanReview, HumanReviewDecision, Investigation } from '../../api'

type HumanReviewPanelProps = {
  investigation: Investigation
  incidentTitle: string
  onResolve: (investigation: Investigation, decision: HumanReviewDecision) => Promise<unknown>
}

type DecisionKind = HumanReviewDecision['decision']

const REVIEW_TYPE_LABELS: Record<HumanReview['review_type'], string> = {
  JIRA_WRITE: 'Jira write',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  CONFLICTING_EVIDENCE: 'Conflicting evidence',
}

const FIELD_LABELS: Record<string, string> = {
  summary: 'Issue summary',
  description: 'Issue description',
  commentBody: 'Comment',
}

/** Read the Jira tool call stored in the review draft without trusting its shape. */
function readJiraDraft(review: HumanReview) {
  const toolName = typeof review.draft.tool_name === 'string' ? review.draft.tool_name : null
  const rawArguments = review.draft.arguments
  const args = rawArguments && typeof rawArguments === 'object' && !Array.isArray(rawArguments)
    ? rawArguments as Record<string, unknown>
    : {}
  const rawEditable = review.draft.editable_fields
  const editableFields = Array.isArray(rawEditable)
    ? rawEditable.filter((field): field is string => typeof field === 'string')
    : []
  return { toolName, args, editableFields }
}

function displayValue(value: unknown) {
  if (typeof value === 'string') return value || 'Not set'
  return JSON.stringify(value)
}

/**
 * One paused investigation and the explicit operator decision that resumes it.
 *
 * Nothing is approved by default: the operator must click a decision. For a Jira write, only
 * the text fields listed by the backend can be edited; the target (site, project, issue) is
 * shown read-only.
 */
export function HumanReviewPanel({ investigation, incidentTitle, onResolve }: HumanReviewPanelProps) {
  const review = investigation.human_review!
  const { toolName, args, editableFields } = readJiraDraft(review)
  const isJiraWrite = review.review_type === 'JIRA_WRITE'

  const initialEdits = Object.fromEntries(editableFields.map((field) => [field, displayValue(args[field] ?? '')]))
  const [edits, setEdits] = useState<Record<string, string>>(initialEdits)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState<DecisionKind | null>(null)
  const [showTrace, setShowTrace] = useState(false)

  const changedFields = Object.fromEntries(
    Object.entries(edits).filter(([field, value]) => value !== initialEdits[field]),
  )
  const hasEdits = Object.keys(changedFields).length > 0
  const readOnlyArguments = Object.entries(args).filter(([name]) => !editableFields.includes(name))

  async function submit(decision: DecisionKind) {
    if (decision !== 'APPROVE' && !reason.trim()) {
      setError(decision === 'REJECT' ? 'Explain why you reject this decision.' : 'Write the information you need.')
      return
    }
    setError(null)
    setSubmitting(decision)
    try {
      await onResolve(investigation, {
        decision,
        actor: 'local-operator',
        ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(decision === 'APPROVE' && hasEdits ? { edited_draft: changedFields } : {}),
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The decision could not be submitted.')
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <li className="proposal-card human-review-panel" aria-label={`Review for ${incidentTitle}`}>
      <div className="proposal-heading">
        <div>
          <p>{REVIEW_TYPE_LABELS[review.review_type]}</p>
          <h3>{incidentTitle}</h3>
        </div>
        <span className="lifecycle lifecycle-awaiting_human_review">Awaiting review</span>
      </div>

      <p className="review-reason">{review.reason}</p>
      {review.evidence_references.length > 0 && (
        <p className="review-evidence"><strong>Evidence references:</strong> {review.evidence_references.join(', ')}</p>
      )}

      {isJiraWrite && (
        <div className="review-draft">
          {toolName && <p className="review-tool"><strong>Requested Jira tool:</strong> <code>{toolName}</code></p>}
          {readOnlyArguments.length > 0 && (
            <dl className="proposal-payload" aria-label="Fixed Jira target">
              {readOnlyArguments.map(([name, value]) => (
                <div key={name}><dt>{name}</dt><dd>{displayValue(value)}</dd></div>
              ))}
            </dl>
          )}
          {editableFields.map((field) => (
            <label className="review-field" key={field}>
              {FIELD_LABELS[field] ?? field}
              <textarea
                onChange={(event) => setEdits((current) => ({ ...current, [field]: event.target.value }))}
                rows={field === 'summary' ? 2 : 5}
                value={edits[field] ?? ''}
              />
            </label>
          ))}
        </div>
      )}

      <details className="review-trace" onToggle={(event) => setShowTrace(event.currentTarget.open)}>
        <summary>How the agents got here</summary>
        {showTrace && <AgentTrace compact investigation={investigation} />}
      </details>

      <div className="proposal-actions">
        <label>
          Reason or question for the agent (required to reject or request information)
          <textarea onChange={(event) => setReason(event.target.value)} rows={2} value={reason} />
        </label>
        {error && <p className="proposal-error" role="alert">{error}</p>}
        <div>
          <button className="primary-button" disabled={submitting !== null} onClick={() => void submit('APPROVE')} type="button">
            {submitting === 'APPROVE' ? 'Resuming…' : hasEdits ? 'Approve with edits' : 'Approve and resume'}
          </button>
          <button className="quiet-button" disabled={submitting !== null} onClick={() => void submit('REQUEST_INFORMATION')} type="button">
            Request information
          </button>
          <button className="danger-button" disabled={submitting !== null} onClick={() => void submit('REJECT')} type="button">
            Reject
          </button>
        </div>
      </div>
    </li>
  )
}
