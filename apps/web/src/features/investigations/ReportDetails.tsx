import type { InvestigationReport } from '../../api'

export function ReportDetails({ report }: { report: InvestigationReport }) {
  const evidence = report.evidence ?? []
  const hypotheses = report.hypotheses ?? []
  const actions = report.proposed_actions ?? []
  const limitations = report.limitations ?? []

  return (
    <section className="investigation-report" aria-label="Investigation report">
      <div className="report-heading">
        <div><p>INVESTIGATION REPORT</p><h2>Evidence and recommendations</h2></div>
        <span className="confidence">Confidence {Math.round(report.confidence * 100)}%</span>
      </div>
      <p className="report-summary">{report.summary}</p>
      <div className="report-agents"><strong>Specialists consulted</strong>{report.agents_consulted?.length ? report.agents_consulted.join(' · ') : 'Not recorded'}</div>
      <div className="report-grid">
        <section className="report-section"><h3>Observed evidence</h3>{evidence.length > 0 ? <ul className="evidence-list">{evidence.map((item, index) => <li key={`${item.source}-${index}`}><div><strong>{item.source}</strong><span>{item.source_status}</span></div><p>{item.detail}</p></li>)}</ul> : <p>No evidence was returned.</p>}</section>
        <section className="report-section"><h3>Hypotheses</h3>{hypotheses.length > 0 ? <ul>{hypotheses.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>No hypotheses were returned.</p>}</section>
        <section className="report-section"><h3>Proposed actions</h3>{actions.length > 0 ? <ol>{actions.map((item, index) => <li key={index}>{item}</li>)}</ol> : <p>No actions were proposed.</p>}</section>
        <section className="report-section"><h3>Limitations</h3>{limitations.length > 0 ? <ul>{limitations.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>No limitations were reported.</p>}</section>
      </div>
    </section>
  )
}
