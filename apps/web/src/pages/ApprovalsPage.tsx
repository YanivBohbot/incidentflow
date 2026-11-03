import type { HumanReviewDecision, Incident, Investigation } from '../api'
import { EmptyState } from '../components/ui/EmptyState'
import { HumanReviewPanel } from '../features/approvals/HumanReviewPanel'

type ApprovalsPageProps = {
  incidents: Incident[]
  investigations: Investigation[]
  onResolve: (investigation: Investigation, decision: HumanReviewDecision) => Promise<Investigation>
}

/** Show only workflow interruptions that require an explicit operator decision. */
export function ApprovalsPage({ incidents, investigations, onResolve }: ApprovalsPageProps) {
  const pendingReviews = investigations.filter((item) => item.lifecycle === 'AWAITING_HUMAN_REVIEW' && item.human_review)
  const incidentTitle = (investigation: Investigation) => (
    incidents.find((incident) => incident.id === investigation.incident_id)?.title ?? 'Source incident unavailable'
  )

  return (
    <section className="surface approvals-surface">
      <div className="section-heading">
        <p>OPERATOR REVIEW</p>
        <h2>Pending workflow decisions</h2>
        <span>Each decision resumes the same durable investigation. A Jira write is executed only after you approve its exact tool call.</span>
      </div>
      {pendingReviews.length === 0 ? (
        <EmptyState description="The system has no paused investigations. New reviews appear here only when a workflow needs an operator decision." title="No decisions pending" />
      ) : (
        <ul className="proposal-list">
          {pendingReviews.map((investigation) => (
            <HumanReviewPanel
              incidentTitle={incidentTitle(investigation)}
              investigation={investigation}
              key={`${investigation.id}:${investigation.human_review!.id}`}
              onResolve={onResolve}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
