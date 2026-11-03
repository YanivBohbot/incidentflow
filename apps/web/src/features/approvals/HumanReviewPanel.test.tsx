import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { HumanReview, Investigation } from '../../api'
import { HumanReviewPanel } from './HumanReviewPanel'

function pausedInvestigation(review: Partial<HumanReview> = {}): Investigation {
  return {
    id: 'inv-1',
    incident_id: 'inc-1',
    lifecycle: 'AWAITING_HUMAN_REVIEW',
    report: null,
    error_message: null,
    created_at: '2026-11-03T00:00:00Z',
    updated_at: '2026-11-03T00:00:00Z',
    human_review: {
      id: 'review-1',
      review_type: 'JIRA_WRITE',
      reason: 'Jira issue creation requires operator approval.',
      evidence_references: ['alarms:active'],
      draft: {
        tool_name: 'createJiraIssue',
        arguments: { cloudId: 'cloud-1', projectKey: 'SAM1', summary: 'Payment API errors', description: 'HTTP 500' },
        editable_fields: ['summary', 'description'],
      },
      ...review,
    },
  }
}

function renderPanel(investigation = pausedInvestigation(), onResolve = vi.fn().mockResolvedValue(undefined)) {
  render(<ul><HumanReviewPanel incidentTitle="Payment API outage" investigation={investigation} onResolve={onResolve} /></ul>)
  return { onResolve, user: userEvent.setup() }
}

describe('HumanReviewPanel', () => {
  it('shows the Jira target read-only and only the permitted text fields as editable', () => {
    renderPanel()

    expect(screen.getByText('createJiraIssue')).toBeInTheDocument()
    expect(screen.getByText('SAM1')).toBeInTheDocument()
    expect(screen.getByLabelText('Issue summary')).toHaveValue('Payment API errors')
    expect(screen.getByLabelText('Issue description')).toHaveValue('HTTP 500')
    expect(screen.getAllByRole('textbox')).toHaveLength(3) // summary, description, reason
  })

  it('never resolves without an explicit click', () => {
    const { onResolve } = renderPanel()

    expect(onResolve).not.toHaveBeenCalled()
  })

  it('approves without edited_draft when nothing changed', async () => {
    const { onResolve, user } = renderPanel()

    await user.click(screen.getByRole('button', { name: 'Approve and resume' }))

    expect(onResolve).toHaveBeenCalledWith(expect.objectContaining({ id: 'inv-1' }), {
      decision: 'APPROVE',
      actor: 'local-operator',
    })
  })

  it('sends only the changed fields when the operator edits the draft', async () => {
    const { onResolve, user } = renderPanel()

    const summary = screen.getByLabelText('Issue summary')
    await user.clear(summary)
    await user.type(summary, 'Payment API HTTP 500 after deploy 184')
    await user.click(screen.getByRole('button', { name: 'Approve with edits' }))

    expect(onResolve).toHaveBeenCalledWith(expect.anything(), {
      decision: 'APPROVE',
      actor: 'local-operator',
      edited_draft: { summary: 'Payment API HTTP 500 after deploy 184' },
    })
  })

  it('requires a reason before rejecting or requesting information', async () => {
    const { onResolve, user } = renderPanel()

    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Explain why you reject this decision.')
    await user.click(screen.getByRole('button', { name: 'Request information' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Write the information you need.')
    expect(onResolve).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText(/Reason or question/), 'Which deploy?')
    await user.click(screen.getByRole('button', { name: 'Request information' }))
    expect(onResolve).toHaveBeenCalledWith(expect.anything(), {
      decision: 'REQUEST_INFORMATION',
      actor: 'local-operator',
      reason: 'Which deploy?',
    })
  })

  it('shows the API error and keeps the review usable when the backend refuses', async () => {
    const onResolve = vi.fn().mockRejectedValue(new Error('These Jira fields cannot be edited: projectKey.'))
    const { user } = renderPanel(pausedInvestigation(), onResolve)

    await user.click(screen.getByRole('button', { name: 'Approve and resume' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('These Jira fields cannot be edited: projectKey.')
    expect(screen.getByRole('button', { name: 'Approve and resume' })).toBeEnabled()
  })

  it('shows no Jira editor for an evidence review', () => {
    renderPanel(pausedInvestigation({ review_type: 'INSUFFICIENT_EVIDENCE', reason: 'No deploy correlation.', draft: {} }))

    expect(screen.getByText('Insufficient evidence')).toBeInTheDocument()
    expect(screen.queryByLabelText('Issue summary')).not.toBeInTheDocument()
  })
})
