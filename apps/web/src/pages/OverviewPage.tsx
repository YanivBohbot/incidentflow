import type { Incident, Investigation, OperationalMetrics, Readiness } from '../api'

type OverviewPageProps = {
  incidents: Incident[]
  investigations: Investigation[]
  metrics: {
    incidentCount: number
    pendingApprovalCount: number
    runningInvestigationCount: number
  }
  operationalMetrics: OperationalMetrics
  readiness: Readiness
}

const capabilities = [
  { title: 'Investigation Supervisor', description: 'Routes each request to only the specialists that supply relevant evidence.', detail: 'LangGraph workflow · structured report' },
  { title: 'Jira MCP', description: 'Reads incidents and creates Jira issues only after a human approves the exact tool call.', detail: 'Read + approval-gated write' },
  { title: 'MongoDB MCP', description: 'Inspects live operational events through a restricted read-only tool set.', detail: 'Read-only evidence' },
  { title: 'Knowledge retrieval', description: 'Searches procedures and reviewed incident lessons stored in Pinecone.', detail: 'RAG · curated memory' },
  { title: 'GitHub MCP', description: 'Examines approved repositories, commits, and pull requests without changing code.', detail: 'Read-only code context' },
  { title: 'AWS CloudWatch MCP', description: 'Reads alarms, metrics, and allowlisted log groups through a read-only IAM role.', detail: 'Read-only production signals' },
  { title: 'Durable workflow state', description: 'PostgreSQL checkpoints preserve investigation context and resume a paused approval safely.', detail: 'Short-term workflow memory' },
]

/** Show the implemented system boundaries alongside live, non-sensitive operating state. */
export function OverviewPage({ incidents, investigations, metrics, operationalMetrics, readiness }: OverviewPageProps) {
  const latestInvestigations = investigations.slice(0, 4)
  // Count persisted investigations; the operational metrics counter restarts with the API.
  const completedCount = investigations.filter((item) => item.lifecycle === 'COMPLETED').length
  const requestCount = Object.values(operationalMetrics.requests_by_status).reduce((total, count) => total + count, 0)

  return <div className="overview-page">
    <section className="overview-hero surface">
      <div><p className="eyebrow">INCIDENTFLOW CONTROL CENTER</p><h2>Evidence-led incident response, with people in control of every write.</h2><span>The system captures incidents, dynamically selects specialist agents, correlates evidence, and pauses before sensitive Jira actions.</span></div>
      <div className={`readiness-card readiness-${readiness.status}`}><span className="status-dot" /><div><strong>{readiness.status === 'ready' ? 'Operationally ready' : 'Starting services'}</strong><small>Workflow checkpoint: {readiness.checkpointer ?? 'initializing'}</small></div></div>
    </section>

    <section className="overview-stat-grid" aria-label="Operational summary">
      <article><span>Recorded incidents</span><strong>{metrics.incidentCount}</strong><small>{incidents.length === 1 ? 'incident in this workspace' : 'incidents in this workspace'}</small></article>
      <article><span>Completed investigations</span><strong>{completedCount}</strong><small>persisted workflow outcomes</small></article>
      <article><span>Awaiting approval</span><strong>{metrics.pendingApprovalCount}</strong><small>operator decisions required</small></article>
      <article><span>Observed API requests</span><strong>{requestCount}</strong><small>non-sensitive in-process counter</small></article>
    </section>

    <section className="overview-section"><div className="section-heading"><p>IMPLEMENTED CAPABILITIES</p><h2>What the platform can do today</h2><span>Each integration has a narrow responsibility and its own safety boundary.</span></div><div className="capability-grid">{capabilities.map((capability) => <article className="capability-card" key={capability.title}><small>{capability.detail}</small><h3>{capability.title}</h3><p>{capability.description}</p></article>)}</div></section>

    <section className="overview-section overview-two-column">
      <article className="surface workflow-map"><div className="section-heading"><p>WORKFLOW</p><h2>How one investigation progresses</h2></div><ol><li><strong>Capture</strong><span>Record a real operational incident.</span></li><li><strong>Investigate</strong><span>The Supervisor calls only relevant specialist tools.</span></li><li><strong>Correlate</strong><span>Evidence, hypotheses, limitations, and actions remain separated.</span></li><li><strong>Review</strong><span>Jira writes pause with their exact arguments for human approval.</span></li><li><strong>Learn</strong><span>An operator may store only a confirmed root cause and resolution.</span></li></ol></article>
      <article className="surface recent-outcomes"><div className="section-heading"><p>RECENT OUTCOMES</p><h2>Latest investigations</h2></div>{latestInvestigations.length === 0 ? <p className="muted-copy">No investigation has completed yet.</p> : <ul>{latestInvestigations.map((investigation) => <li key={investigation.id}><span className={`lifecycle lifecycle-${investigation.lifecycle.toLowerCase()}`}>{investigation.lifecycle.replaceAll('_', ' ')}</span><p>{investigation.report?.summary ?? investigation.error_message ?? 'No report was returned.'}</p></li>)}</ul>}</article>
    </section>
  </div>
}
