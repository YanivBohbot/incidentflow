/** Root component: page navigation, workspace metrics, and the active page. */
import { useState } from 'react'
import { AppShell } from './components/layout/AppShell'
import type { AppPage } from './components/layout/AppShell'
import { MetricCard } from './components/ui/MetricCard'
import { useIncidentFlow } from './hooks/useIncidentFlow'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { HistoryPage } from './pages/HistoryPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { InvestigationsPage } from './pages/InvestigationsPage'
import { OverviewPage } from './pages/OverviewPage'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('overview')
  const [isCreateIncidentFormOpen, setIsCreateIncidentFormOpen] = useState(false)
  const workspace = useIncidentFlow(activePage)
  const [journalIncidentId, setJournalIncidentId] = useState<string | undefined>(undefined)
  const [journalRequest, setJournalRequest] = useState(0)
  const [fromHistory, setFromHistory] = useState(false)

  function viewJournal(incidentId: string) {
    setJournalIncidentId(incidentId)
    setJournalRequest((value) => value + 1)
    setActivePage('history')
  }

  /** Any navigation other than "Open investigation" forgets the way back to the history. */
  function changePage(page: AppPage) {
    setFromHistory(false)
    setActivePage(page)
  }

  function openInvestigation(investigationId: string) {
    const investigation = workspace.investigations.find((item) => item.id === investigationId)
    if (investigation) workspace.selectInvestigation(investigation)
    setFromHistory(true)
    setActivePage('investigations')
  }

  async function handleStartInvestigation() {
    setActivePage('investigations')
    const investigation = await workspace.startInvestigation()
    if (investigation) {
      setActivePage(investigation.lifecycle === 'AWAITING_HUMAN_REVIEW' ? 'approvals' : 'investigations')
    }
  }

  return (
    <AppShell activePage={activePage} onCreateIncident={() => { setActivePage('incidents'); setIsCreateIncidentFormOpen(true) }} onPageChange={changePage} pendingApprovalCount={workspace.metrics.pendingApprovalCount} statusMessage={workspace.statusMessage}>
      {activePage !== 'history' && <section className="metrics" aria-label="Workspace metrics">
        <MetricCard description="Recorded in this workspace" label="Open incidents" value={workspace.metrics.incidentCount} />
        <MetricCard description="Fixed or closed" label="Resolved incidents" value={workspace.metrics.resolvedIncidentCount} />
        <MetricCard description="Currently processing evidence" label="Investigations running" value={workspace.metrics.runningInvestigationCount} />
        <MetricCard description="Explicit operator decisions needed" label="Pending approvals" value={workspace.metrics.pendingApprovalCount} />
      </section>}
      {workspace.isLoading ? <div className="surface loading-state">Loading IncidentFlow workspace…</div> : <>
        {activePage === 'overview' && <OverviewPage
          incidents={workspace.incidents}
          investigations={workspace.investigations}
          metrics={workspace.metrics}
          operationalMetrics={workspace.operationalMetrics}
          readiness={workspace.readiness}
        />}
        {activePage === 'incidents' && <IncidentsPage demoEnabled={workspace.demoEnabled} isDemoStarting={workspace.isDemoStarting} onAutoStartDemo={workspace.autoStartDemo} onRunDemo={workspace.startDemoRun} incidents={workspace.incidents} investigations={workspace.investigations} isCreateFormOpen={isCreateIncidentFormOpen} isStartingInvestigation={workspace.isStartingInvestigation} onCloseCreateForm={() => setIsCreateIncidentFormOpen(false)} onCreateIncident={workspace.createIncident} onSelectIncident={workspace.setSelectedIncident} onStartInvestigation={handleStartInvestigation} onViewJournal={viewJournal} selectedIncident={workspace.selectedIncident} />}
        {activePage === 'investigations' && <InvestigationsPage incidents={workspace.incidents} investigations={workspace.investigations} onConfirmLesson={workspace.confirmIncidentLesson} onResolveIncident={workspace.resolveIncident} onBackToHistory={fromHistory ? () => changePage('history') : undefined} onViewJournal={viewJournal} onSelectInvestigation={workspace.selectInvestigation} selectedInvestigation={workspace.selectedInvestigation} />}
        {activePage === 'approvals' && <ApprovalsPage incidents={workspace.incidents} investigations={workspace.investigations} onResolve={workspace.resolveHumanReview} />}
        <div hidden={activePage !== 'history'}>
          <HistoryPage active={activePage === 'history'} focusIncidentId={journalIncidentId} focusRequest={journalRequest} incidents={workspace.incidents} investigations={workspace.investigations} onOpenInvestigation={openInvestigation} />
        </div>
      </>}
    </AppShell>
  )
}

export default App
