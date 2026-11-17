import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../api'
import { InvestigationsPage } from './InvestigationsPage'

vi.mock('../features/investigations/AgentTrace', () => ({ AgentTrace: () => null }))

const incident = (status: string) =>
  ({ id: 'inc', title: 'Checkout down', priority: 'CRITICAL', status, description: 'd', created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z' }) as Incident
const completed = { id: 'inv', incident_id: 'inc', lifecycle: 'COMPLETED', created_at: '2026-11-17T10:00:00Z', report: null } as unknown as Investigation

function renderPage(status: string, onResolveIncident = vi.fn(async () => undefined), onConfirmLesson = vi.fn()) {
  render(<InvestigationsPage incidents={[incident(status)]} investigations={[completed]} onConfirmLesson={onConfirmLesson} onResolveIncident={onResolveIncident} onSelectInvestigation={vi.fn()} selectedInvestigation={completed} />)
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

  it('hides the lesson form until the incident is resolved', async () => {
    renderPage('OPEN')
    expect(screen.queryByRole('region', { name: 'Confirm incident lesson for memory' })).toBeNull()
    cleanup()

    renderPage('RESOLVED')
    expect(screen.queryByRole('region', { name: 'Confirm incident lesson for memory' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save what fixed it as a lesson' }))
    expect(screen.getByRole('region', { name: 'Confirm incident lesson for memory' })).toBeInTheDocument()
  })

  it('closes the lesson form and confirms once the lesson is saved to memory', async () => {
    const onConfirmLesson = vi.fn(async () => ({ state: 'CONFIRMED' }))
    renderPage('RESOLVED', undefined, onConfirmLesson)

    await userEvent.click(screen.getByRole('button', { name: 'Save what fixed it as a lesson' }))
    await userEvent.type(screen.getByLabelText('Affected service'), 'checkout-api')
    await userEvent.type(screen.getByLabelText('Confirmed root cause'), 'Pool exhausted')
    await userEvent.type(screen.getByLabelText('Validated resolution'), 'Raised the pool size')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm lesson for memory' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Lesson saved to memory')
    expect(screen.queryByRole('region', { name: 'Confirm incident lesson for memory' })).toBeNull()
  })

  it('keeps the form open with the error when indexing fails', async () => {
    const onConfirmLesson = vi.fn(async () => ({ state: 'FAILED', index_error: 'Pinecone unavailable' }))
    renderPage('RESOLVED', undefined, onConfirmLesson)

    await userEvent.click(screen.getByRole('button', { name: 'Save what fixed it as a lesson' }))
    await userEvent.type(screen.getByLabelText('Affected service'), 'checkout-api')
    await userEvent.type(screen.getByLabelText('Confirmed root cause'), 'Pool exhausted')
    await userEvent.type(screen.getByLabelText('Validated resolution'), 'Raised the pool size')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm lesson for memory' }))

    expect(await screen.findByText(/Pinecone unavailable/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Confirm incident lesson for memory' })).toBeInTheDocument()
  })
})
