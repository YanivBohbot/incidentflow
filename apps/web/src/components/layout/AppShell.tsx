import type { ReactNode } from 'react'

export type AppPage = 'overview' | 'incidents' | 'investigations' | 'approvals'

type NavigationItem = {
  id: AppPage
  label: string
  description: string
  /** One sentence shown under the page title: what this page is for. */
  intro: string
}

const navigation: NavigationItem[] = [
  {
    id: 'overview',
    label: 'Overview',
    description: 'System architecture and live operating state',
    intro: 'A read-only dashboard: incidents, running investigations, pending decisions, and system health.',
  },
  {
    id: 'incidents',
    label: 'Incidents',
    description: 'Capture and investigate operational issues',
    intro: 'Report a problem you observed, then select it and launch the multi-agent investigation.',
  },
  {
    id: 'investigations',
    label: 'Investigations',
    description: 'Review evidence and recommendations',
    intro: 'Read each investigation report and follow, step by step, which agents worked and what they found.',
  },
  {
    id: 'approvals',
    label: 'Approvals',
    description: 'Resume paused workflow decisions',
    intro: 'The agents are paused here. Read what they want to do, edit it if needed, then approve or reject.',
  },
]

type AppShellProps = {
  activePage: AppPage
  onPageChange: (page: AppPage) => void
  statusMessage: string
  onCreateIncident: () => void
  pendingApprovalCount: number
  children: ReactNode
}

export function AppShell({ activePage, onPageChange, statusMessage, onCreateIncident, pendingApprovalCount, children }: AppShellProps) {
  const current = navigation.find((item) => item.id === activePage)
  const showApprovalBanner = pendingApprovalCount > 0 && activePage !== 'approvals'

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">IF</span><div><strong>IncidentFlow</strong><small>Operations console</small></div></div>
        <nav className="primary-navigation">
          {navigation.map((item) => (
            <button aria-current={activePage === item.id ? 'page' : undefined} className={activePage === item.id ? 'is-active' : ''} key={item.id} onClick={() => onPageChange(item.id)} type="button">
              <span className="nav-label">
                {item.label}
                {item.id === 'approvals' && pendingApprovalCount > 0 && (
                  <b aria-label={`${pendingApprovalCount} pending`} className="nav-badge">{pendingApprovalCount}</b>
                )}
              </span>
              <small>{item.description}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-status"><span className="status-dot" /><div><strong>Workspace connected</strong><small>{statusMessage}</small></div></div>
      </aside>
      <section className="workspace">
        {showApprovalBanner && (
          <div className="approval-banner" role="status">
            <span aria-hidden="true">⏸</span>
            <p>
              <strong>{pendingApprovalCount === 1 ? '1 decision is waiting for you.' : `${pendingApprovalCount} decisions are waiting for you.`}</strong>
              {' '}The agents are paused until an operator approves or rejects.
            </p>
            <button className="primary-button" onClick={() => onPageChange('approvals')} type="button">Review now</button>
          </div>
        )}
        <header className="topbar">
          <div>
            <p>INCIDENT RESPONSE PLATFORM</p>
            <h1>{current?.label}</h1>
            <span className="page-intro">{current?.intro}</span>
          </div>
          <button className="primary-button" onClick={onCreateIncident} type="button">Report incident</button>
        </header>
        {children}
      </section>
    </main>
  )
}
