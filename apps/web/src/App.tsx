import { useState } from 'react'
import { AppShell } from './components/layout/AppShell'
import type { AppPage } from './components/layout/AppShell'
import { MetricCard } from './components/ui/MetricCard'
import { useIncidentFlow } from './hooks/useIncidentFlow'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { InvestigationsPage } from './pages/InvestigationsPage'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('incidents')
  const [isCreateIncidentFormOpen, setIsCreateIncidentFormOpen] = useState(false)
  const workspace = useIncidentFlow()

  async function handleStartInvestigation() {
    const investigation = await workspace.startInvestigation()
    if (investigation) setActivePage('investigations')
  }

  async function handleApproveProposal(proposal: Parameters<typeof workspace.approveProposal>[0]) {
    const confirmed = window.confirm(`Approve and execute ${proposal.action.replace('_', ' ').toLowerCase()} in Jira? This cannot be undone by IncidentFlow.`)
    if (confirmed) await workspace.approveProposal(proposal)
  }

  return (
    <AppShell activePage={activePage} onCreateIncident={() => { setActivePage('incidents'); setIsCreateIncidentFormOpen(true) }} onPageChange={setActivePage} statusMessage={workspace.statusMessage}>
      <section className="metrics" aria-label="Workspace metrics">
        <MetricCard description="Recorded in this workspace" label="Open incidents" value={workspace.metrics.incidentCount} />
        <MetricCard description="Currently processing evidence" label="Investigations running" value={workspace.metrics.runningInvestigationCount} />
        <MetricCard description="Explicit operator decisions needed" label="Pending approvals" value={workspace.metrics.pendingApprovalCount} />
      </section>
      {workspace.isLoading ? <div className="surface loading-state">Loading IncidentFlow workspace…</div> : <>{activePage === 'incidents' && <IncidentsPage incidents={workspace.incidents} isCreateFormOpen={isCreateIncidentFormOpen} onCloseCreateForm={() => setIsCreateIncidentFormOpen(false)} onCreateIncident={workspace.createIncident} onSelectIncident={workspace.setSelectedIncident} onStartInvestigation={handleStartInvestigation} selectedIncident={workspace.selectedIncident} />}{activePage === 'investigations' && <InvestigationsPage incidents={workspace.incidents} investigations={workspace.investigations} onSelectInvestigation={workspace.selectInvestigation} selectedInvestigation={workspace.selectedInvestigation} />}{activePage === 'approvals' && <ApprovalsPage onApprove={(proposal) => void handleApproveProposal(proposal)} onCancel={(proposal, reason) => void workspace.cancelProposal(proposal, reason)} onProposeComment={workspace.proposeJiraComment} onProposeIssue={workspace.proposeJiraIssue} onReject={(proposal, reason) => void workspace.rejectProposal(proposal, reason)} proposals={workspace.proposals} selectedInvestigation={workspace.selectedInvestigation} />}</>}
    </AppShell>
  )
}

export default App
