import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api'
import type { JiraCommentProposalInput, JiraIssueProposalInput, JiraIssueTypeOption, JiraProjectOption, JiraResourceOption } from '../../api'

type ProposalComposerProps = {
  onProposeComment: (data: JiraCommentProposalInput) => Promise<void>
  onProposeIssue: (data: JiraIssueProposalInput) => Promise<void>
}

type ProposalKind = 'issue' | 'comment'

export function ProposalComposer({ onProposeComment, onProposeIssue }: ProposalComposerProps) {
  const [kind, setKind] = useState<ProposalKind>('issue')
  const [cloudId, setCloudId] = useState('')
  const [projectKey, setProjectKey] = useState('')
  const [issueType, setIssueType] = useState('Incident')
  const [summary, setSummary] = useState('')
  const [description, setDescription] = useState('')
  const [issueIdOrKey, setIssueIdOrKey] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [resources, setResources] = useState<JiraResourceOption[]>([])
  const [projects, setProjects] = useState<JiraProjectOption[]>([])
  const [issueTypes, setIssueTypes] = useState<JiraIssueTypeOption[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)

  useEffect(() => {
    let isCurrent = true
    void api.listJiraResources()
      .then((items) => { if (isCurrent) { setResources(items); setCloudId((current) => current || items[0]?.cloud_id || '') } })
      .catch((error: unknown) => { if (isCurrent) setCatalogError(error instanceof Error ? error.message : 'Could not load Jira resources.') })
    return () => { isCurrent = false }
  }, [])

  useEffect(() => {
    if (!cloudId) return
    let isCurrent = true
    void api.listJiraProjects(cloudId)
      .then((items) => { if (isCurrent) { setProjects(items); setProjectKey((current) => items.some((item) => item.key === current) ? current : items[0]?.key || '') } })
      .catch((error: unknown) => { if (isCurrent) setCatalogError(error instanceof Error ? error.message : 'Could not load Jira projects.') })
    return () => { isCurrent = false }
  }, [cloudId])

  useEffect(() => {
    if (!cloudId || !projectKey) return
    let isCurrent = true
    void api.listJiraIssueTypes(cloudId, projectKey)
      .then((items) => { if (isCurrent) { setIssueTypes(items); setIssueType((current) => items.some((item) => item.name === current) ? current : items[0]?.name || '') } })
      .catch((error: unknown) => { if (isCurrent) setCatalogError(error instanceof Error ? error.message : 'Could not load Jira issue types.') })
    return () => { isCurrent = false }
  }, [cloudId, projectKey])

  function selectCloud(nextCloudId: string) {
    setCloudId(nextCloudId)
    setProjectKey('')
    setIssueType('')
    setProjects([])
    setIssueTypes([])
  }

  function selectProject(nextProjectKey: string) {
    setProjectKey(nextProjectKey)
    setIssueType('')
    setIssueTypes([])
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    try {
      if (kind === 'issue') {
        await onProposeIssue({ cloudId, projectKey, issueType, summary, description })
        setSummary('')
        setDescription('')
      } else {
        await onProposeComment({ cloudId, issueIdOrKey, commentBody })
        setCommentBody('')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="proposal-composer" aria-label="Create Jira action proposal">
      <div className="section-heading"><p>PREPARE A JIRA ACTION</p><h2>Create a pending proposal</h2><span>The form only stores the action for human review. It does not contact Jira.</span></div>
      <div className="proposal-kind-switch" role="tablist" aria-label="Proposal type"><button aria-selected={kind === 'issue'} className={kind === 'issue' ? 'is-active' : ''} onClick={() => setKind('issue')} role="tab" type="button">Create issue</button><button aria-selected={kind === 'comment'} className={kind === 'comment' ? 'is-active' : ''} onClick={() => setKind('comment')} role="tab" type="button">Add comment</button></div>
      <form className="proposal-form" onSubmit={handleSubmit}>
        <label>Jira site<select disabled={resources.length === 0} onChange={(event) => selectCloud(event.target.value)} required value={cloudId}><option value="">Select a Jira site</option>{resources.map((item) => <option key={item.cloud_id} value={item.cloud_id}>{item.url ?? item.cloud_id}</option>)}</select></label>
        {catalogError && <p className="catalog-error">{catalogError}</p>}
        {kind === 'issue' ? <><label>Project<select disabled={!cloudId || projects.length === 0} onChange={(event) => selectProject(event.target.value)} required value={projectKey}><option value="">Select a project</option>{projects.map((item) => <option key={item.key} value={item.key}>{item.key} · {item.name}</option>)}</select></label><label>Issue type<select disabled={!projectKey || issueTypes.length === 0} onChange={(event) => setIssueType(event.target.value)} required value={issueType}><option value="">Select an issue type</option>{issueTypes.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label><label>Summary<input maxLength={255} onChange={(event) => setSummary(event.target.value)} placeholder="Brief issue summary" required value={summary} /></label><label>Description<textarea maxLength={10000} onChange={(event) => setDescription(event.target.value)} placeholder="Evidence, impact and recommended next steps" required rows={5} value={description} /></label></> : <><label>Issue key or ID<input onChange={(event) => setIssueIdOrKey(event.target.value)} placeholder="e.g. SCRUM-5" required value={issueIdOrKey} /></label><label>Comment body<textarea maxLength={10000} onChange={(event) => setCommentBody(event.target.value)} placeholder="Investigation update to add to the Jira issue" required rows={5} value={commentBody} /></label></>}
        <button className="secondary-button" disabled={isSubmitting} type="submit">{isSubmitting ? 'Saving proposal…' : 'Save proposal for approval'}</button>
      </form>
    </section>
  )
}
