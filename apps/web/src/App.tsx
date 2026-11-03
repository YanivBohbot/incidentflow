import { useState } from 'react'
import { AppShell } from './components/layout/AppShell'
import type { AppPage } from './components/layout/AppShell'
import { MetricCard } from './components/ui/MetricCard'
import { useIncidentFlow } from './hooks/useIncidentFlow'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { InvestigationsPage } from './pages/InvestigationsPage'
import { OverviewPage } from './pages/OverviewPage'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('overview')
  const [isCreateIncidentFormOpen, setIsCreateIncidentFormOpen] = useState(false)
  const workspace = useIncidentFlow()

  async function handleStartInvestigation() {
    setActivePage('investigations') // watch the agents work while the workflow runs
    const investigation = await workspace.startInvestigation()
    if (investigation) {
      setActivePage(investigation.lifecycle === 'AWAITING_HUMAN_REVIEW' ? 'approvals' : 'investigations')
    }
  }

  return (
    <AppShell activePage={activePage} onCreateIncident={() => { setActivePage('incidents'); setIsCreateIncidentFormOpen(true) }} onPageChange={setActivePage} pendingApprovalCount={workspace.metrics.pendingApprovalCount} statusMessage={workspace.statusMessage}>
      <section className="metrics" aria-label="Workspace metrics">
        <MetricCard description="Recorded in this workspace" label="Open incidents" value={workspace.metrics.incidentCount} />
        <MetricCard description="Currently processing evidence" label="Investigations running" value={workspace.metrics.runningInvestigationCount} />
        <MetricCard description="Explicit operator decisions needed" label="Pending approvals" value={workspace.metrics.pendingApprovalCount} />
      </section>
      {workspace.isLoading ? <div className="surface loading-state">Loading IncidentFlow workspace…</div> : <>
        {activePage === 'overview' && <OverviewPage
          incidents={workspace.incidents}
          investigations={workspace.investigations}
          metrics={workspace.metrics}
          operationalMetrics={workspace.operationalMetrics}
          readiness={workspace.readiness}
        />}
        {activePage === 'incidents' && <IncidentsPage incidents={workspace.incidents} investigations={workspace.investigations} isCreateFormOpen={isCreateIncidentFormOpen} onCloseCreateForm={() => setIsCreateIncidentFormOpen(false)} onCreateIncident={workspace.createIncident} onSelectIncident={workspace.setSelectedIncident} onStartInvestigation={handleStartInvestigation} selectedIncident={workspace.selectedIncident} />}
        {activePage === 'investigations' && <InvestigationsPage incidents={workspace.incidents} investigations={workspace.investigations} onConfirmLesson={workspace.confirmIncidentLesson} onSelectInvestigation={workspace.selectInvestigation} selectedInvestigation={workspace.selectedInvestigation} />}
        {activePage === 'approvals' && <ApprovalsPage incidents={workspace.incidents} investigations={workspace.investigations} onResolve={workspace.resolveHumanReview} />}
      </>}
    </AppShell>
  )
}

export default App
