import { useState } from 'react'
import type { JiraProposal } from '../../api'

const proposalFieldLabels: Record<string, string> = {
  cloudId: 'Jira cloud ID',
  projectKey: 'Project key',
  issueType: 'Issue type',
  summary: 'Summary',
  description: 'Description',
  issueIdOrKey: 'Issue key',
  commentBody: 'Comment body',
}

type ProposalReviewProps = {
  proposal: JiraProposal
  onApprove: (proposal: JiraProposal) => void
  onReject: (proposal: JiraProposal, reason: string) => void
  onCancel: (proposal: JiraProposal, reason: string) => void
}

export function ProposalReview({ proposal, onApprove, onReject, onCancel }: ProposalReviewProps) {
  const isPending = proposal.state === 'PENDING'
  const [reason, setReason] = useState('')

  return (
    <li className="proposal-card">
      <div className="proposal-heading"><div><p>JIRA ACTION</p><h3>{proposal.action === 'CREATE_ISSUE' ? 'Create issue' : 'Add comment'}</h3></div><span className={`proposal-state proposal-state-${proposal.state.toLowerCase()}`}>{proposal.state}</span></div>
      {isPending && <p className="proposal-warning">Approval will send exactly the content below to Jira.</p>}
      <dl className="proposal-payload">{Object.entries(proposal.payload).map(([key, value]) => <div key={key}><dt>{proposalFieldLabels[key] ?? key}</dt><dd>{value}</dd></div>)}</dl>
      {isPending && <div className="proposal-actions"><label>Decision note (optional)<textarea onChange={(event) => setReason(event.target.value)} placeholder="Explain a rejection or cancellation" rows={2} value={reason} /></label><div><button className="primary-button" onClick={() => onApprove(proposal)} type="button">Approve and execute in Jira</button><button className="danger-button" onClick={() => onReject(proposal, reason)} type="button">Reject</button><button className="quiet-button" onClick={() => onCancel(proposal, reason)} type="button">Cancel</button></div></div>}
      {proposal.error_message && <p className="proposal-error">{proposal.error_message}</p>}
      {proposal.result_payload && <p className="proposal-result">Jira returned: {JSON.stringify(proposal.result_payload.result)}</p>}
      <div className="proposal-audit"><strong>Audit trail</strong><span>Proposed by {proposal.proposed_by}</span><ul>{proposal.decision_history.map((entry, index) => <li key={`${entry.event}-${entry.at}-${index}`}><b>{entry.event}</b> · {entry.actor} · {new Date(entry.at).toLocaleString()}{entry.reason ? ` · ${entry.reason}` : ''}</li>)}</ul></div>
    </li>
  )
}
