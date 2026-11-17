import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../api'
import { InvestigationsPage } from './InvestigationsPage'

vi.mock('../features/investigations/AgentTrace', () => ({ AgentTrace: () => null }))

const incident = (status: string) =>
  ({ id: 'inc', title: 'Checkout down', priority: 'CRITICAL', status, description: 'd', created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z' }) as Incident
const completed = { id: 'inv', incident_id: 'inc', lifecycle: 'COMPLETED', created_at: '2026-11-17T10:00:00Z', report: null } as unknown as Investigation

function renderPage(status: string, onResolveIncident = vi.fn(async () => undefined)) {
  render(<InvestigationsPage incidents={[incident(status)]} investigations={[completed]} onConfirmLesson={vi.fn()} onResolveIncident={onResolveIncident} onSelectInvestigation={vi.fn()} selectedInvestigation={completed} />)
  return onResolveIncident
}

afterEach(cleanup)

describe('InvestigationsPage resolve banner', () => {
  it('lets the operator resolve the incident once its investigation is complete', async () => {
    const onResolveIncident = renderPage('OPEN')

    await userEvent.click(screen.getByRole('button', { name: 'Mark incident resolved' }))

    expect(onResolveIncident).toHaveBeenCalledWith('inc')
  })

  it('shows the incident as resolved instead of the button', () => {
    renderPage('RESOLVED')

    expect(screen.queryByRole('button', { name: 'Mark incident resolved' })).toBeNull()
    expect(screen.getByText('Incident resolved.')).toBeInTheDocument()
  })
})
