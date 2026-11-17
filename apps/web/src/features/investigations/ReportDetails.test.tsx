import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { InvestigationReport } from '../../api'
import { ReportDetails, sourceName } from './ReportDetails'

const report: InvestigationReport = {
  summary: 'checkout-api returns HTTP 503 for 40% of customers.',
  confidence: 0.9,
  root_cause: 'The database connection pool is exhausted by flash-sale traffic.',
  causal_chain: [
    { label: 'Traffic spike', detail: 'Requests rose from 400 to 2100 per second.', source: 'data_intelligence', verified: true },
    { label: 'Pool exhausted', detail: '200 of 200 connections in use.', source: 'cloudwatch', verified: true },
    { label: 'HTTP 503 for customers', detail: '42% of POST /checkout fail.', source: 'cloudwatch', verified: false },
  ],
  evidence: [
    { source: 'ask_cloudwatch', detail: 'PoolTimeoutError waited 5000 ms.', source_status: 'live' },
    { source: 'ask_data_intelligence', detail: 'rps 400 -> 2100.', source_status: 'simulated' },
  ],
  hypotheses: ['Raising max pods multiplied the connections.'],
  proposed_actions: ['Raise the pool size', 'Cap the autoscaler', 'Add a pool alarm', 'Write a runbook'],
  limitations: [],
}

afterEach(cleanup)

describe('ReportDetails', () => {
  it('leads with the root cause and the causal chain from origin to symptom', () => {
    render(<ReportDetails report={report} />)

    expect(screen.getByText(report.root_cause!)).toBeInTheDocument()
    const steps = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')
    expect(steps.map((step) => step.querySelector('strong')?.textContent)).toEqual(['Traffic spike', 'Pool exhausted', 'HTTP 503 for customers'])
    expect(steps[0]).toHaveTextContent('Origin')
    expect(steps[2]).toHaveTextContent('Symptom')
    expect(steps[2]).toHaveTextContent('hypothesis')
  })

  it('shows the evidence behind the step the operator clicks', async () => {
    render(<ReportDetails report={report} />)

    await userEvent.click(screen.getByRole('button', { name: /Pool exhausted/ }))

    const selected = screen.getByRole('region', { name: 'Selected step' })
    expect(selected).toHaveTextContent('200 of 200 connections in use.')
    expect(selected).toHaveTextContent('Observed by CloudWatch')
    expect(selected).toHaveTextContent('PoolTimeoutError waited 5000 ms.')
    expect(selected).not.toHaveTextContent('rps 400 -> 2100.')
  })

  it('shows three actions first and the rest on demand', async () => {
    render(<ReportDetails report={report} />)

    expect(screen.queryByText('Write a runbook')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Show all 4 actions' }))
    expect(screen.getByText('Write a runbook')).toBeInTheDocument()
  })

  it('falls back to the summary for reports written before the causal chain', () => {
    render(<ReportDetails report={{ ...report, root_cause: null, causal_chain: undefined }} />)

    expect(screen.getByText(report.summary)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Causal chain' })).toBeNull()
  })

  it('keeps the next-actions box visible when no action was proposed', () => {
    render(<ReportDetails report={{ ...report, proposed_actions: [] }} />)

    expect(screen.getByRole('region', { name: 'What to do next' })).toHaveTextContent('proposed no action')
  })

  it('names each source the same way whatever the agent called it', () => {
    expect(sourceName('ask_cloudwatch')).toBe('CloudWatch')
    expect(sourceName('CloudWatch Observability Agent')).toBe('CloudWatch')
    expect(sourceName('data_intelligence')).toBe('MongoDB events')
    expect(sourceName('operational_events collection in incidentflow_dev database')).toBe('MongoDB events')
    expect(sourceName('GitHub YanivBohbot/incidentflow repository')).toBe('GitHub')
    expect(sourceName('checkout-api connection pool runbook')).toBe('Knowledge base')
  })
})
