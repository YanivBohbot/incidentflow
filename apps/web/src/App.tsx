import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { api } from './api'
import type { Incident, Investigation } from './api'

function App() {
  const [section, setSection] = useState('Incidents')
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [message, setMessage] = useState('Connecting to the IncidentFlow API…')

  useEffect(() => {
    api.listIncidents().then((items) => { setIncidents(items); setMessage('API connected') }).catch((error: Error) => setMessage(error.message))
  }, [])

  async function createIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    try {
      const incident = await api.createIncident({ title: String(form.get('title')), description: String(form.get('description')), priority: String(form.get('priority')) as Incident['priority'] })
      setIncidents((items) => [incident, ...items]); setSelectedIncident(incident); setMessage('Incident created. You can now start an investigation.'); formElement.reset()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not create incident.') }
  }

  async function startInvestigation() {
    if (!selectedIncident) return
    setMessage('Running the investigation workflow…')
    try { const result = await api.startInvestigation(selectedIncident.id, selectedIncident.description); setInvestigation(result); setSection('Investigations'); setMessage('Investigation completed.') } catch (error) { setMessage(error instanceof Error ? error.message : 'Investigation failed.') }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar"><b>IF · IncidentFlow</b>{['Incidents', 'Investigations', 'Approvals'].map((item) => <button className={section === item ? 'active' : ''} key={item} onClick={() => setSection(item)} type="button">{item}</button>)}</aside>
      <section className="workspace"><header><div><p>OPERATIONS WORKSPACE</p><h1>{section}</h1></div><button type="button" onClick={() => setSection('Incidents')}>New incident</button></header><div className="metrics"><article>Open incidents<strong>{incidents.length}</strong></article><article>Investigations running<strong>{investigation?.lifecycle === 'RUNNING' ? 1 : 0}</strong></article><article>Pending approvals<strong>0</strong></article></div><article className="panel"><p>API STATUS</p><h2>{message}</h2>{section === 'Incidents' && <><form onSubmit={createIncident}><input name="title" minLength={5} placeholder="Incident title" required /><textarea name="description" minLength={10} placeholder="Describe the operational impact" required /><select name="priority" defaultValue="MEDIUM"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><button type="submit">Create incident</button></form><ul>{incidents.map((incident) => <li key={incident.id}><button type="button" onClick={() => setSelectedIncident(incident)}>{incident.title} · {incident.priority}</button></li>)}</ul>{selectedIncident && <button type="button" onClick={startInvestigation}>Start investigation for {selectedIncident.title}</button>}</>}{section === 'Investigations' && <div>{investigation ? <><h2>{investigation.lifecycle}</h2><p>{investigation.report?.summary ?? investigation.error_message ?? 'No report returned.'}</p></> : 'Select an incident and start an investigation.'}</div>}{section === 'Approvals' && <div>Jira actions will appear here only after the authenticated HITL flow is enabled.</div>}</article></section>
    </main>
  )
}

export default App
