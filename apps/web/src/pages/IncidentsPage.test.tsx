import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../api'
import { IncidentsPage } from './IncidentsPage'

const incident = (id: string, title: string, priority: Incident['priority'], created_at: string) =>
  ({ id, title, priority, created_at, description: 'd', status: 'OPEN', updated_at: created_at }) as Incident

const incidents = [
  incident('low', 'Email delays', 'LOW', '2026-11-03T10:00:00Z'),
  incident('crit', 'Checkout down', 'CRITICAL', '2026-11-03T09:00:00Z'),
  incident('high', 'Login failures', 'HIGH', '2026-11-03T11:00:00Z'),
]
const investigations = [
  { id: 'i1', incident_id: 'crit', lifecycle: 'COMPLETED' } as Investigation,
]

function renderPage() {
  render(
    <IncidentsPage incidents={incidents} investigations={investigations} isCreateFormOpen={false} onCloseCreateForm={vi.fn()} onCreateIncident={vi.fn()} onSelectIncident={vi.fn()} onStartInvestigation={vi.fn()} selectedIncident={null} />,
  )
}

describe('IncidentsPage queue', () => {
  it('lists the most severe incident first and shows its latest investigation state', () => {
    renderPage()

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('strong')?.textContent)).toEqual(['Checkout down', 'Login failures', 'Email delays'])
    expect(items[0]).toHaveTextContent('Investigated')
    expect(items[1]).toHaveTextContent('Not investigated')
  })

  it('filters the queue by severity', async () => {
    renderPage()

    await userEvent.setup().click(screen.getByRole('button', { name: /^High/ }))

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items).toHaveLength(1)
    expect(items[0]).toHaveTextContent('Login failures')
    expect(screen.getByRole('button', { name: /^High/ })).toHaveAttribute('aria-pressed', 'true')
  })
})
