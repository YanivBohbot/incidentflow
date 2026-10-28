import type { ReactNode } from 'react'

export type AppPage = 'incidents' | 'investigations' | 'approvals'

type NavigationItem = {
  id: AppPage
  label: string
  description: string
}

const navigation: NavigationItem[] = [
  { id: 'incidents', label: 'Incidents', description: 'Capture and investigate operational issues' },
  { id: 'investigations', label: 'Investigations', description: 'Review evidence and recommendations' },
  { id: 'approvals', label: 'Approvals', description: 'Control proposed Jira actions' },
]

type AppShellProps = {
  activePage: AppPage
  onPageChange: (page: AppPage) => void
  statusMessage: string
  onCreateIncident: () => void
  children: ReactNode
}

export function AppShell({ activePage, onPageChange, statusMessage, onCreateIncident, children }: AppShellProps) {
  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">IF</span><div><strong>IncidentFlow</strong><small>Operations console</small></div></div>
        <nav className="primary-navigation">
          {navigation.map((item) => <button aria-current={activePage === item.id ? 'page' : undefined} className={activePage === item.id ? 'is-active' : ''} key={item.id} onClick={() => onPageChange(item.id)} type="button"><span>{item.label}</span><small>{item.description}</small></button>)}
        </nav>
        <div className="sidebar-status"><span className="status-dot" /><div><strong>Workspace connected</strong><small>{statusMessage}</small></div></div>
      </aside>
      <section className="workspace">
        <header className="topbar"><div><p>INCIDENT RESPONSE PLATFORM</p><h1>{navigation.find((item) => item.id === activePage)?.label}</h1></div><button className="primary-button" onClick={onCreateIncident} type="button">Report incident</button></header>
        {children}
      </section>
    </main>
  )
}
