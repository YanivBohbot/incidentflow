import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { Incident, IncidentEvent } from '../api'
import { DECISION_KINDS, HistoryPage } from './HistoryPage'

const incident = { id: 'inc-1', title: 'Checkout down' } as Incident

const event = (overrides: Partial<IncidentEvent>): IncidentEvent => ({
  id: 'e', incident_id: 'inc-1', investigation_id: null, kind: 'INCIDENT_CREATED',
  occurred_at: '2026-11-17T12:00:00Z', actor: 'system', summary: 'Incident created',
  details: {}, reconstructed: false, incident_title: 'Checkout down', ...overrides,
})

const history = [
  event({ id: 'e3', kind: 'INCIDENT_RESOLVED', summary: 'Marked resolved by alice', occurred_at: '2026-11-17T12:30:00Z' }),
  event({ id: 'e2', kind: 'REVIEW_DECIDED', summary: 'Jira write approved by alice', occurred_at: '2026-11-17T12:10:00Z', investigation_id: 'inv-1' }),
  event({ id: 'e1', summary: 'Incident created', reconstructed: true }),
]

function mockApi(nextBefore: string | null = null) {
  const getHistory = vi.spyOn(api, 'getHistory').mockResolvedValue({ events: history, next_before: nextBefore })
  const getIncidentEvents = vi.spyOn(api, 'getIncidentEvents').mockResolvedValue([...history].reverse())
  return { getHistory, getIncidentEvents }
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('HistoryPage', () => {
  it('renders the chronology newest first with incident titles', async () => {
    mockApi()
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    const rows = within(await screen.findByRole('list', { name: 'Chronology' })).getAllByRole('listitem')
    expect(rows.map((row) => row.querySelector('strong')?.textContent)).toEqual([
      'Marked resolved by alice', 'Jira write approved by alice', 'Incident created',
    ])
    expect(rows[0]).toHaveTextContent('Checkout down')
  })

  it('decisions-only chip filters to decision kinds', async () => {
    const { getHistory } = mockApi()
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Decisions only' }))

    expect(getHistory).toHaveBeenLastCalledWith({ incidentId: undefined, kinds: DECISION_KINDS, before: undefined })
    expect(DECISION_KINDS).toEqual(['REVIEW_DECIDED', 'INCIDENT_RESOLVED', 'LESSON_SAVED'])
  })

  it('selecting an event shows that incident journal oldest first', async () => {
    const { getIncidentEvents } = mockApi()
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    const rows = within(await screen.findByRole('list', { name: 'Chronology' })).getAllByRole('listitem')
    await userEvent.click(within(rows[0]).getByRole('button'))

    expect(getIncidentEvents).toHaveBeenCalledWith('inc-1')
    const journal = await within(screen.getByRole('list', { name: 'Journal' })).findAllByRole('listitem')
    expect(journal[0]).toHaveTextContent('Incident created')
    expect(journal[2]).toHaveTextContent('Marked resolved by alice')
  })

  it('reconstructed events show an approximate time marker', async () => {
    mockApi()
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    const rows = within(await screen.findByRole('list', { name: 'Chronology' })).getAllByRole('listitem')
    expect(rows[2]).toHaveTextContent('≈')
    expect(rows[0]).not.toHaveTextContent('≈')
  })

  it('load more requests the next page with before', async () => {
    const { getHistory } = mockApi('cursor-1')
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(getHistory).toHaveBeenLastCalledWith({ incidentId: undefined, kinds: undefined, before: 'cursor-1' })
  })

  it('the periodic refresh keeps the older pages already loaded', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const older = event({ id: 'e0', summary: 'Older event', occurred_at: '2026-11-16T09:00:00Z' })
    const newest = event({ id: 'e4', summary: 'Newest event', occurred_at: '2026-11-17T13:00:00Z' })
    const getHistory = vi.spyOn(api, 'getHistory')
      .mockResolvedValueOnce({ events: history, next_before: 'cursor-1' })
      .mockResolvedValueOnce({ events: [older], next_before: null })
      .mockResolvedValue({ events: [newest, ...history], next_before: 'cursor-1' })
    vi.spyOn(api, 'getIncidentEvents').mockResolvedValue([])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<HistoryPage incidents={[incident]} onOpenInvestigation={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: 'Load more' }))
    await screen.findByText('Older event')
    await vi.advanceTimersByTimeAsync(10_000)
    await screen.findByText('Newest event')

    const rows = within(screen.getByRole('list', { name: 'Chronology' })).getAllByRole('listitem')
    expect(rows.map((row) => row.querySelector('strong')?.textContent)).toEqual([
      'Newest event', 'Marked resolved by alice', 'Jira write approved by alice', 'Incident created', 'Older event',
    ])
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(getHistory).toHaveBeenCalledTimes(3)
    vi.useRealTimers()
  })

  it('open investigation calls onOpenInvestigation from the journal', async () => {
    mockApi()
    const onOpenInvestigation = vi.fn()
    render(<HistoryPage incidents={[incident]} initialIncidentId="inc-1" onOpenInvestigation={onOpenInvestigation} />)

    const journal = await within(screen.getByRole('list', { name: 'Journal' })).findAllByRole('listitem')
    await userEvent.click(within(journal[1]).getByRole('button', { name: 'Open investigation' }))

    expect(onOpenInvestigation).toHaveBeenCalledWith('inv-1')
  })
})
