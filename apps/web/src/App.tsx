import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { api } from './api'
import type { Incident, Investigation, JiraProposal } from './api'

function App() {
  const [section, setSection] = useState('Incidents')
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [selectedInvestigation, setSelectedInvestigation] = useState<Investigation | null>(null)
  const [proposals, setProposals] = useState<JiraProposal[]>([])
  const [message, setMessage] = useState('Connecting to the IncidentFlow API…')

  async function refreshInvestigations() {
    const items = await api.listInvestigations()
    setInvestigations(items)
    return items
  }

  async function loadProposals(investigation: Investigation | null) {
    if (!investigation) {
      setProposals([])
      return
    }
    setProposals(await api.listJiraProposals(investigation.id))
  }

  useEffect(() => {
    Promise.all([api.listIncidents(), refreshInvestigations()])
      .then(([incidentItems]) => {
        setIncidents(incidentItems)
        setMessage('API connected')
      })
      .catch((error: Error) => setMessage(error.message))
  }, [])

  useEffect(() => {
    loadProposals(selectedInvestigation).catch((error: Error) => setMessage(error.message))
  }, [selectedInvestigation])

  async function createIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    try {
      const incident = await api.createIncident({
        title: String(form.get('title')),
        description: String(form.get('description')),
        priority: String(form.get('priority')) as Incident['priority'],
      })
      setIncidents((items) => [incident, ...items])
      setSelectedIncident(incident)
      setMessage('Incident created. You can now start an investigation.')
      formElement.reset()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create incident.')
    }
  }

  async function startInvestigation() {
    if (!selectedIncident) return
    setMessage('Running the investigation workflow…')
    try {
      const result = await api.startInvestigation(selectedIncident.id, selectedIncident.description)
      setSelectedInvestigation(result)
      setInvestigations((items) => [result, ...items.filter((item) => item.id !== result.id)])
      setSection('Investigations')
      setMessage(result.lifecycle === 'COMPLETED' ? 'Investigation completed.' : 'Investigation finished with a failure.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Investigation failed.')
      await refreshInvestigations()
    }
  }

  function selectInvestigation(investigation: Investigation) {
    setSelectedInvestigation(investigation)
    setSection('Investigations')
  }

  async function approveProposal(proposal: JiraProposal) {
    const confirmed = window.confirm(
      `Approve and execute ${proposal.action.replace('_', ' ').toLowerCase()} in Jira? This cannot be undone by IncidentFlow.`,
    )
    if (!confirmed) return

    setMessage('Executing the approved Jira action…')
    try {
      const updated = await api.approveJiraProposal(proposal.id)
      setProposals((items) => items.map((item) => (item.id === updated.id ? updated : item)))
      setMessage(updated.state === 'EXECUTED' ? 'Jira action executed.' : `Jira action failed: ${updated.error_message ?? 'Unknown error.'}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not approve the Jira action.')
    }
  }

  const pendingApprovals = proposals.filter((proposal) => proposal.state === 'PENDING').length

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <b>IF · IncidentFlow</b>
        {['Incidents', 'Investigations', 'Approvals'].map((item) => <button className={section === item ? 'active' : ''} key={item} onClick={() => setSection(item)} type="button">{item}</button>)}
      </aside>
      <section className="workspace">
        <header><div><p>OPERATIONS WORKSPACE</p><h1>{section}</h1></div><button type="button" onClick={() => setSection('Incidents')}>New incident</button></header>
        <div className="metrics">
          <article>Open incidents<strong>{incidents.length}</strong></article>
          <article>Investigations running<strong>{investigations.filter((item) => item.lifecycle === 'RUNNING').length}</strong></article>
          <article>Pending approvals<strong>{pendingApprovals}</strong></article>
        </div>
        <article className="panel">
          <p>API STATUS</p><h2>{message}</h2>
          {section === 'Incidents' && <><form onSubmit={createIncident}><input name="title" minLength={5} placeholder="Incident title" required /><textarea name="description" minLength={10} placeholder="Describe the operational impact" required /><select name="priority" defaultValue="MEDIUM"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><button type="submit">Create incident</button></form><ul>{incidents.map((incident) => <li key={incident.id}><button type="button" onClick={() => setSelectedIncident(incident)}>{incident.title} · {incident.priority}</button></li>)}</ul>{selectedIncident && <button type="button" onClick={startInvestigation}>Start investigation for {selectedIncident.title}</button>}</>}
          {section === 'Investigations' && <div><ul className="selection-list">{investigations.map((item) => <li key={item.id}><button type="button" onClick={() => selectInvestigation(item)}>{item.lifecycle} · {item.incident_id}</button></li>)}</ul>{selectedInvestigation && <><h2>{selectedInvestigation.lifecycle}</h2><p>{selectedInvestigation.report?.summary ?? selectedInvestigation.error_message ?? 'No report returned.'}</p></>}</div>}
          {section === 'Approvals' && <div>{!selectedInvestigation && <p>Select an investigation first to review its Jira action proposals.</p>}{selectedInvestigation && <><p>Review each stored action before it can contact Jira.</p><ul className="proposal-list">{proposals.map((proposal) => <li key={proposal.id}><strong>{proposal.action.replace('_', ' ')}</strong><span>{proposal.state}</span><p>{proposal.payload.summary ?? proposal.payload.commentBody ?? 'No summary available.'}</p>{proposal.state === 'PENDING' && <button type="button" onClick={() => approveProposal(proposal)}>Approve and execute in Jira</button>}{proposal.error_message && <p>{proposal.error_message}</p>}</li>)}</ul>{proposals.length === 0 && <p>No Jira proposals for this investigation.</p>}</>}</div>}
        </article>
      </section>
    </main>
  )
}

export default App
