import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../api'
import { ApprovalsPage } from './ApprovalsPage'

const base = { incident_id: 'inc-1', report: null, error_message: null, created_at: '', updated_at: '' }
const incident = { id: 'inc-1', title: 'Payment API outage' } as Incident

describe('ApprovalsPage', () => {
  it('lists only investigations awaiting a human review', () => {
    const investigations: Investigation[] = [
      { ...base, id: 'done', lifecycle: 'COMPLETED', human_review: null },
      {
        ...base,
        id: 'paused',
        lifecycle: 'AWAITING_HUMAN_REVIEW',
        human_review: {
          id: 'r1',
          review_type: 'CONFLICTING_EVIDENCE',
          reason: 'GitHub and CloudWatch disagree.',
          evidence_references: [],
          draft: {},
        },
      },
    ]

    render(<ApprovalsPage incidents={[incident]} investigations={investigations} onResolve={vi.fn()} />)

    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('GitHub and CloudWatch disagree.')).toBeInTheDocument()
    expect(screen.getByText('Payment API outage')).toBeInTheDocument()
  })

  it('shows an empty state when nothing is paused', () => {
    render(<ApprovalsPage incidents={[]} investigations={[]} onResolve={vi.fn()} />)

    expect(screen.getByText('No decisions pending')).toBeInTheDocument()
  })
})
