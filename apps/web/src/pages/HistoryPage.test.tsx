import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { Incident, IncidentEvent, Investigation } from '../api'
import { DECISION_KINDS, HistoryPage } from './HistoryPage'

const incident = (id: string, title: string, service: string | null, status = 'OPEN') => ({ id, title, service, status, created_at: '2026-11-17T12:00:00Z' }) as Incident
const incidents = [
  incident('inc-1', 'Checkout down', 'checkout-api'),
  incident('inc-2', 'Checkout down again', 'checkout-api'),
  incident('inc-3', 'Login failures', 'auth-service'),
  incident('inc-4', 'Printer on fire', null),
  incident('inc-5', 'Checkout down, untouched', 'checkout-api', 'CLOSED'),
]
const investigations = [{ id: 'inv-1', incident_id: 'inc-2' }] as Investigation[]

const event = (overrides: Partial<IncidentEvent>): IncidentEvent => ({
  id: 'e', incident_id: 'inc-1', investigation_id: null, kind: 'INCIDENT_CREATED',
  occurred_at: '2026-11-17T12:00:00Z', actor: 'system', summary: 'Incident created',
  details: {}, reconstructed: false, incident_title: 'Checkout down', incident_service: 'checkout-api', ...overrides,
})

const history = [
  event({ id: 'e5', kind: 'INCIDENT_RESOLVED', summary: 'Marked resolved by alice', occurred_at: '2026-11-17T12:30:00Z' }),
  event({ id: 'e4', incident_id: 'inc-3', incident_title: 'Login failures', incident_service: 'auth-service', summary: 'Login alarm raised', occurred_at: '2026-11-17T12:20:00Z' }),
  event({ id: 'e3', incident_id: 'inc-2', incident_title: 'Checkout down again', summary: 'Jira write approved by alice', kind: 'REVIEW_DECIDED', investigation_id: 'inv-1', occurred_at: '2026-11-17T12:10:00Z' }),
  event({ id: 'e2', incident_id: null, incident_title: null, incident_service: null, kind: 'DEMO_RUN_STARTED', summary: 'Demo run started', occurred_at: '2026-11-17T12:05:00Z' }),
  event({ id: 'e1', summary: 'Incident created', reconstructed: true }),
]

function mockApi(nextBefore: string | null = null) {
  const getHistory = vi.spyOn(api, 'getHistory').mockResolvedValue({ events: history, next_before: nextBefore })
  const getIncidentEvents = vi.spyOn(api, 'getIncidentEvents').mockResolvedValue([history[4], history[0]])
  return { getHistory, getIncidentEvents }
}

function renderPage(props: Partial<Parameters<typeof HistoryPage>[0]> = {}) {
  return render(<HistoryPage incidents={incidents} investigations={investigations} onOpenInvestigation={vi.fn()} {...props} />)
}

const group = (name: string) => screen.findByRole('region', { name })
const summaries = (element: HTMLElement) =>
  within(element).queryAllByRole('listitem').map((row) => row.querySelector('strong')?.textContent)

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('HistoryPage', () => {
  it('groups events by service, one card per incident with its events in time order', async () => {
    mockApi()
    renderPage()

    const checkout = await group('checkout-api')
    const cards = within(checkout).getAllByRole('article')
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual(['Checkout down', 'Checkout down again'])
    expect(summaries(cards[0])).toEqual(['Incident created', 'Marked resolved by alice'])
    expect(summaries(cards[1])).toEqual(['Jira write approved by alice'])
    const names = screen.getAllByRole('region').map((region) => region.getAttribute('aria-label'))
    expect(names).toEqual(['checkout-api', 'auth-service', 'Demo runs'])
  })

  it('opens the most recent category and folds the others', async () => {
    mockApi()
    renderPage()

    expect(summaries(await group('checkout-api'))).toHaveLength(3)
    expect(summaries(await group('auth-service'))).toHaveLength(0)
    await userEvent.click(within(await group('auth-service')).getByRole('button', { name: /auth-service/ }))
    expect(summaries(await group('auth-service'))).toEqual(['Login alarm raised'])
  })

  it('shows short category chips with incident counts', async () => {
    mockApi()
    renderPage()

    const filters = screen.getByRole('group', { name: 'Filter history' })
    expect(within(filters).getByRole('button', { name: 'checkout-api 2' })).toBeInTheDocument()
    await userEvent.click(within(filters).getByRole('button', { name: 'Show untouched' }))
    expect(within(filters).getByRole('button', { name: 'checkout-api 3' })).toBeInTheDocument()
    expect(within(filters).getByRole('button', { name: 'auth-service 1' })).toBeInTheDocument()
    expect(within(filters).getByRole('button', { name: 'Printer on fire 1' })).toBeInTheDocument()
  })

  it('a category chip loads only that category', async () => {
    const { getHistory } = mockApi()
    renderPage()

    await userEvent.click(screen.getByRole('button', { name: 'auth-service 1' }))

    expect(getHistory).toHaveBeenLastCalledWith({ category: 'auth-service', kinds: undefined, hideUntouched: true, before: undefined })
  })

  it('the decisions chip filters to decision kinds', async () => {
    const { getHistory } = mockApi()
    renderPage()

    await userEvent.click(screen.getByRole('button', { name: 'Decisions' }))

    expect(getHistory).toHaveBeenLastCalledWith({ category: undefined, kinds: DECISION_KINDS, hideUntouched: true, before: undefined })
    expect(DECISION_KINDS).toEqual(['REVIEW_DECIDED', 'INCIDENT_RESOLVED', 'LESSON_SAVED'])
  })

  it('hides incidents closed without investigation unless asked', async () => {
    const { getHistory } = mockApi()
    renderPage()

    await screen.findByRole('region', { name: 'checkout-api' })
    expect(getHistory).toHaveBeenLastCalledWith({ category: undefined, kinds: undefined, hideUntouched: true, before: undefined })
    await userEvent.click(screen.getByRole('button', { name: 'Show untouched' }))
    expect(getHistory).toHaveBeenLastCalledWith({ category: undefined, kinds: undefined, hideUntouched: false, before: undefined })
  })

  it('more than six categories hide behind a +N chip', async () => {
    mockApi()
    const many = Array.from({ length: 8 }, (_, index) => incident(`m${index}`, `t${index}`, `service-${index}`))
    renderPage({ incidents: many })

    expect(screen.queryByRole('button', { name: 'service-7 1' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '+2' }))
    expect(screen.getByRole('button', { name: 'service-7 1' })).toBeInTheDocument()
  })

  it('selecting an event shows that incident journal, and reconstructed times show ≈', async () => {
    const { getIncidentEvents } = mockApi()
    renderPage()

    const rows = within(await group('checkout-api')).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('≈')
    await userEvent.click(within(rows[0]).getByRole('button'))

    expect(getIncidentEvents).toHaveBeenCalledWith('inc-1')
    const journal = await within(screen.getByRole('list', { name: 'Journal' })).findAllByRole('listitem')
    expect(journal[0]).toHaveTextContent('Incident created')
  })

  it('a journal request from another page selects that incident', async () => {
    const { getIncidentEvents } = mockApi()
    const { rerender } = renderPage()

    rerender(<HistoryPage focusIncidentId="inc-3" focusRequest={1} incidents={incidents} investigations={investigations} onOpenInvestigation={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: 'Login failures' })).toBeInTheDocument()
    expect(getIncidentEvents).toHaveBeenCalledWith('inc-3')
  })

  it('load more requests the next page with before', async () => {
    const { getHistory } = mockApi('cursor-1')
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(getHistory).toHaveBeenLastCalledWith({ category: undefined, kinds: undefined, hideUntouched: true, before: 'cursor-1' })
  })

  it('the periodic refresh keeps the older pages already loaded', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const older = event({ id: 'e0', summary: 'Older event', occurred_at: '2026-11-16T09:00:00Z' })
    const newest = event({ id: 'e9', summary: 'Newest event', occurred_at: '2026-11-17T13:00:00Z' })
    const getHistory = vi.spyOn(api, 'getHistory')
      .mockResolvedValueOnce({ events: history, next_before: 'cursor-1' })
      .mockResolvedValueOnce({ events: [older], next_before: null })
      .mockResolvedValue({ events: [newest, ...history], next_before: 'cursor-1' })
    vi.spyOn(api, 'getIncidentEvents').mockResolvedValue([])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Load more' }))
    await screen.findByText('Older event')
    await vi.advanceTimersByTimeAsync(10_000)
    await screen.findByText('Newest event')

    expect(summaries(within(await group('checkout-api')).getAllByRole('article')[0])).toEqual([
      'Older event', 'Incident created', 'Marked resolved by alice', 'Newest event',
    ])
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(getHistory).toHaveBeenCalledTimes(3)
    vi.useRealTimers()
  })

  it('does not poll while the tab is hidden', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { getHistory } = mockApi()
    renderPage({ active: false })

    await vi.advanceTimersByTimeAsync(30_000)

    expect(getHistory).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('open investigation calls onOpenInvestigation from the journal', async () => {
    mockApi()
    vi.spyOn(api, 'getIncidentEvents').mockResolvedValue([history[2]])
    const onOpenInvestigation = vi.fn()
    renderPage({ focusIncidentId: 'inc-2', focusRequest: 1, onOpenInvestigation })

    const journal = await within(screen.getByRole('list', { name: 'Journal' })).findAllByRole('listitem')
    await userEvent.click(within(journal[0]).getByRole('button', { name: 'Open investigation' }))

    expect(onOpenInvestigation).toHaveBeenCalledWith('inv-1')
  })
})
