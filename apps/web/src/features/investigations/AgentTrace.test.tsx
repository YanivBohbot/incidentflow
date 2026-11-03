import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api'
import type { Investigation, TraceStep } from '../../api'
import { AgentTrace } from './AgentTrace'

const investigation = {
  id: 'inv-1', incident_id: 'inc-1', lifecycle: 'AWAITING_HUMAN_REVIEW', report: null,
  human_review: null, error_message: null, created_at: '', updated_at: '',
} as Investigation

const step = (overrides: Partial<TraceStep>): TraceStep => ({
  kind: 'delegation', actor: 'Investigation Supervisor', title: '', detail: '',
  status: 'info', confidence: null, data: {}, ...overrides,
})

afterEach(() => vi.restoreAllMocks())

describe('AgentTrace', () => {
  it('shows each delegation, finding, and the pending human review in order', async () => {
    vi.spyOn(api, 'getInvestigationTrace').mockResolvedValue([
      step({ kind: 'request', actor: 'Operator', title: 'Incident request', detail: 'HTTP 500' }),
      step({ title: 'Delegated to CloudWatch Observability Agent' }),
      step({ kind: 'finding', actor: 'CloudWatch Observability Agent', title: 'CloudWatch Observability Agent returned its finding', status: 'live', confidence: 0.7 }),
      step({ kind: 'review_pause', actor: 'Human-in-the-loop middleware', title: 'Paused before createJiraIssue — waiting for the operator', status: 'pending' }),
    ])

    render(<AgentTrace investigation={investigation} />)

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(4)
    expect(items[1]).toHaveTextContent('Delegated to CloudWatch Observability Agent')
    expect(items[2]).toHaveTextContent('Live data')
    expect(items[2]).toHaveTextContent('70%')
    expect(items[3]).toHaveTextContent('Waiting for you')
  })

  it('reports a trace loading error', async () => {
    vi.spyOn(api, 'getInvestigationTrace').mockRejectedValue(new Error('Investigation not found'))

    render(<AgentTrace investigation={investigation} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Investigation not found')
  })
})
