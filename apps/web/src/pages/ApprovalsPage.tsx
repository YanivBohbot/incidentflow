import type { Investigation, JiraCommentProposalInput, JiraIssueProposalInput, JiraProposal } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { ProposalComposer } from '../features/approvals/ProposalComposer'
import { ProposalReview } from '../features/approvals/ProposalReview'

type ApprovalsPageProps = {
  selectedInvestigation: Investigation | null
  proposals: JiraProposal[]
  onApprove: (proposal: JiraProposal) => void
  onReject: (proposal: JiraProposal, reason: string) => void
  onCancel: (proposal: JiraProposal, reason: string) => void
  onProposeComment: (data: JiraCommentProposalInput) => Promise<void>
  onProposeIssue: (data: JiraIssueProposalInput) => Promise<void>
}

export function ApprovalsPage({ selectedInvestigation, proposals, onApprove, onReject, onCancel, onProposeComment, onProposeIssue }: ApprovalsPageProps) {
  const [isComposerOpen, setIsComposerOpen] = useState(false)
  if (!selectedInvestigation) return <section className="surface"><EmptyState description="Select an investigation in the Investigations page before reviewing its Jira action proposals." title="Select an investigation first" /></section>
  return <div className="approvals-layout"><section className="surface approvals-surface"><div className="section-heading"><p>STEP 3 · PREPARE</p><h2>Jira action drafts</h2><span>Preparing a draft does not contact Jira. It only saves a proposal for review.</span></div>{isComposerOpen ? <><ProposalComposer onProposeComment={onProposeComment} onProposeIssue={onProposeIssue} /><button className="quiet-button form-cancel" onClick={() => setIsComposerOpen(false)} type="button">Close draft form</button></> : <div className="empty-state"><h2>No need to contact Jira yet?</h2><p>Keep this section closed. Jira options are loaded only when you choose to prepare a new draft.</p><button className="secondary-button" onClick={() => setIsComposerOpen(true)} type="button">Prepare Jira draft</button></div>}</section><section className="surface approvals-surface"><div className="section-heading"><p>STEP 4 · DECIDE</p><h2>Review saved drafts</h2><span>Approve sends the displayed content to Jira. Reject and cancel never contact Jira.</span></div>{proposals.length > 0 ? <ul className="proposal-list">{proposals.map((proposal) => <ProposalReview key={proposal.id} onApprove={onApprove} onCancel={onCancel} onReject={onReject} proposal={proposal} />)}</ul> : <EmptyState description="Prepare a Jira draft only when the investigation requires an external action." title="No drafts awaiting review" />}</section></div>
}
import { useState } from 'react'
