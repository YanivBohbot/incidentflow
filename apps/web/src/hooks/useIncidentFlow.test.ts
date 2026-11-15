import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../api'
import { useIncidentFlow } from './useIncidentFlow'

const incident = {
  id: 'inc-1', title: 'Checkout down', description: 'Checkout is failing', priority: 'HIGH',
  status: 'OPEN', created_at: '2026-11-15T10:00:00Z', updated_at: '2026-11-15T10:00:00Z',
} as Incident

const STEP_TIMES: Record<string, string> = {
  PENDING: '2026-11-15T10:01:00Z',
  RUNNING: '2026-11-15T10:02:00Z',
  AWAITING_HUMAN_REVIEW: '2026-11-15T10:03:00Z',
  COMPLETED: '2026-11-15T10:04:00Z',
}

const investigation = (lifecycle: string, id = 'inv-1'): Investigation => ({
  id, incident_id: 'inc-1', lifecycle, report: null, human_review: null, error_message: null,
  created_at: '2026-11-15T10:01:00Z', updated_at: STEP_TIMES[lifecycle] ?? STEP_TIMES.PENDING,
})

type Handler = (init?: RequestInit) => { status: number, body: unknown }

function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    const handler = routes[key]
    if (!handler) throw new Error(`unexpected request ${key}`)
    const { status, body } = handler(init)
    return new Response(JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const baseRoutes = (listed: () => Investigation[]): Record<string, Handler> => ({
  'GET /api/incidents': () => ({ status: 200, body: [incident] }),
  'GET /api/investigations': () => ({ status: 200, body: listed() }),
  'GET /health/ready': () => ({ status: 200, body: { status: 'ready' } }),
  'GET /operations/metrics': () => ({ status: 200, body: { requests_by_status: {}, investigations_by_lifecycle: {} } }),
})

async function setup(routes: Record<string, Handler>) {
  mockApi(routes)
  const hook = renderHook(() => useIncidentFlow())
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false))
  act(() => hook.result.current.setSelectedIncident(incident))
  return hook
}

describe('useIncidentFlow queued investigations', () => {
  beforeEach(() => { vi.useRealTimers() })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('selects the queued investigation returned by start', async () => {
    const queued = investigation('PENDING')
    const { result } = await setup({
      ...baseRoutes(() => []),
      'POST /api/investigations': () => ({ status: 202, body: queued }),
    })

    await act(async () => { await result.current.startInvestigation() })

    expect(result.current.selectedInvestigation?.id).toBe('inv-1')
    expect(result.current.selectedInvestigation?.lifecycle).toBe('PENDING')
    expect(result.current.statusMessage).toBe('Investigation queued…')
  })

  it('selects the active investigation and explains a 409', async () => {
    const active = investigation('RUNNING', 'inv-active')
    const { result } = await setup({
      ...baseRoutes(() => [active]),
      'POST /api/investigations': () => ({
        status: 409, body: { detail: 'An investigation is already running for this incident.' },
      }),
    })

    await act(async () => { await result.current.startInvestigation() })

    expect(result.current.selectedInvestigation?.id).toBe('inv-active')
    expect(result.current.statusMessage).toBe('An investigation is already running for this incident.')
  })

  it('follows the queued investigation until it completes', async () => {
    let current = investigation('PENDING')
    const { result } = await setup({
      ...baseRoutes(() => [current]),
      'POST /api/investigations': () => ({ status: 202, body: current }),
      'GET /api/investigations/inv-1': () => ({ status: 200, body: current }),
    })
    await act(async () => { await result.current.startInvestigation() })

    current = investigation('RUNNING')
    await waitFor(() => expect(result.current.statusMessage).toBe('Investigation running…'), { timeout: 4000 })
    current = investigation('COMPLETED')
    await waitFor(() => expect(result.current.statusMessage).toBe('Investigation completed.'), { timeout: 4000 })
    expect(result.current.selectedInvestigation?.lifecycle).toBe('COMPLETED')
  })

  it('does not rewind the selection when an older workspace snapshot arrives late', async () => {
    let listed: Investigation[] = []
    const { result } = await setup({
      ...baseRoutes(() => listed),
      'POST /api/investigations': () => ({ status: 202, body: investigation('PENDING') }),
      'GET /api/investigations/inv-1': () => ({ status: 200, body: investigation('COMPLETED') }),
    })
    await act(async () => { await result.current.startInvestigation() })
    await waitFor(() => expect(result.current.statusMessage).toBe('Investigation completed.'), { timeout: 4000 })

    listed = [investigation('RUNNING')]
    await act(async () => { await result.current.refreshWorkspace() })

    expect(result.current.selectedInvestigation?.lifecycle).toBe('COMPLETED')
    expect(result.current.investigations[0].lifecycle).toBe('COMPLETED')
    expect(result.current.statusMessage).toBe('Investigation completed.')
  })

  it('keeps a just-queued row when a list response predates it', async () => {
    const { result } = await setup({
      ...baseRoutes(() => []),
      'POST /api/investigations': () => ({ status: 202, body: investigation('PENDING') }),
    })
    await act(async () => { await result.current.startInvestigation() })
    await act(async () => { await result.current.refreshWorkspace() })

    expect(result.current.investigations.map((item) => item.id)).toEqual(['inv-1'])
  })

  it('sends one start request while a start is in flight', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => { release = resolve })
    const fetchMock = mockApi({
      ...baseRoutes(() => []),
      'POST /api/investigations': () => ({ status: 202, body: investigation('PENDING') }),
    })
    const { result } = renderHook(() => useIncidentFlow())
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    act(() => result.current.setSelectedIncident(incident))
    const routed = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') await gate
      return routed(url, init)
    })

    let first: Promise<unknown> = Promise.resolve()
    let second: Promise<unknown> = Promise.resolve()
    act(() => {
      first = result.current.startInvestigation()
      second = result.current.startInvestigation()
    })
    await waitFor(() => expect(result.current.isStartingInvestigation).toBe(true))
    expect(await second).toBeNull()
    await act(async () => { release(); await first })

    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(result.current.isStartingInvestigation).toBe(false)
  })

  it('accepts the queued response when resolving a review', async () => {
    const paused = investigation('AWAITING_HUMAN_REVIEW')
    const { result } = await setup({
      ...baseRoutes(() => [paused]),
      'POST /api/investigations/inv-1/human-review/resolve': () => ({ status: 202, body: investigation('PENDING') }),
    })

    await act(async () => {
      await result.current.resolveHumanReview(paused, { decision: 'APPROVE', actor: 'op' })
    })

    expect(result.current.statusMessage).toBe('Investigation queued…')
  })
})
