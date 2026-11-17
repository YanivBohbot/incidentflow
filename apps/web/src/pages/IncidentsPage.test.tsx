import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

function renderSelected(isStartingInvestigation: boolean, onStartInvestigation = vi.fn(async () => undefined)) {
  render(
    <IncidentsPage incidents={incidents} investigations={investigations} isCreateFormOpen={false} isStartingInvestigation={isStartingInvestigation} onCloseCreateForm={vi.fn()} onCreateIncident={vi.fn()} onSelectIncident={vi.fn()} onStartInvestigation={onStartInvestigation} selectedIncident={incidents[1]} />,
  )
  return onStartInvestigation
}

describe('IncidentsPage queue', () => {
  it('lists the most severe incident first and shows its latest investigation state', () => {
    renderPage()

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('strong')?.textContent)).toEqual(['Checkout down', 'Login failures', 'Email delays'])
    expect(items[0]).toHaveTextContent('Investigated')
    expect(items[1]).toHaveTextContent('Not investigated')
  })

  it('keeps flagging incidents that nobody has investigated yet', () => {
    renderPage()

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items[0]).not.toHaveClass('needs-attention')
    expect(items[1]).toHaveClass('needs-attention')
    expect(items[2]).toHaveClass('needs-attention')
  })

  it('lists resolved and closed incidents under Resolved, without a launch button', async () => {
    const withResolved = [
      ...incidents,
      { ...incident('done', 'Fixed login', 'HIGH', '2026-11-02T10:00:00Z'), status: 'RESOLVED' } as Incident,
      { ...incident('old', 'Old checkout alarm', 'CRITICAL', '2026-11-02T09:00:00Z'), status: 'CLOSED' } as Incident,
    ]
    render(
      <IncidentsPage incidents={withResolved} investigations={investigations} isCreateFormOpen={false} onCloseCreateForm={vi.fn()} onCreateIncident={vi.fn()} onSelectIncident={vi.fn()} onStartInvestigation={vi.fn()} selectedIncident={withResolved[3]} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /^Resolved/ }))

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('strong')?.textContent)).toEqual(['Fixed login', 'Old checkout alarm'])
    expect(items[0]).toHaveTextContent('Resolved')
    expect(items[1]).toHaveTextContent('Closed')
    expect(items[0]).not.toHaveClass('needs-attention')
    expect(screen.queryByRole('button', { name: 'Launch multi-agent investigation' })).toBeNull()
  })

  it('hides closed and resolved incidents from the list and the counts', () => {
    const withClosed = [
      ...incidents,
      { ...incident('old', 'Old checkout alarm', 'CRITICAL', '2026-11-02T09:00:00Z'), status: 'CLOSED' } as Incident,
      { ...incident('done', 'Fixed login', 'HIGH', '2026-11-02T10:00:00Z'), status: 'RESOLVED' } as Incident,
    ]
    render(
      <IncidentsPage incidents={withClosed} investigations={investigations} isCreateFormOpen={false} onCloseCreateForm={vi.fn()} onCreateIncident={vi.fn()} onSelectIncident={vi.fn()} onStartInvestigation={vi.fn()} selectedIncident={null} />,
    )

    const titles = within(screen.getByRole('list')).getAllByRole('listitem').map((item) => item.querySelector('strong')?.textContent)
    expect(titles).toEqual(['Checkout down', 'Login failures', 'Email delays'])
    expect(screen.getByRole('button', { name: /^All/ })).toHaveTextContent('3')
    expect(screen.getByRole('button', { name: /^Critical/ })).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: /^High/ })).toHaveTextContent('1')
  })

  it('View journal calls onViewJournal with the incident id', async () => {
    const onViewJournal = vi.fn()
    render(
      <IncidentsPage incidents={incidents} investigations={investigations} isCreateFormOpen={false} onCloseCreateForm={vi.fn()} onCreateIncident={vi.fn()} onSelectIncident={vi.fn()} onStartInvestigation={vi.fn()} onViewJournal={onViewJournal} selectedIncident={incidents[1]} />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'View journal' }))

    expect(onViewJournal).toHaveBeenCalledWith('crit')
  })

  it('disables the launch button while the start request is in flight', async () => {
    const onStart = renderSelected(true)

    const launch = screen.getByRole('button', { name: /investigation/i })
    expect(launch).toBeDisabled()
    await userEvent.setup().click(launch)
    expect(onStart).not.toHaveBeenCalled()
  })

  it('launches the investigation when no start is in flight', async () => {
    const onStart = renderSelected(false)

    const launch = screen.getByRole('button', { name: 'Launch multi-agent investigation' })
    expect(launch).toBeEnabled()
    await userEvent.setup().click(launch)
    expect(onStart).toHaveBeenCalledTimes(1)
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

const alarm = (id: string, created_at: string) => ({
  ...incident(id, `Alarm ${id}`, 'HIGH', created_at),
  source: 'CLOUDWATCH_ALARM', service: 'checkout-api', external_id: `arn:${id}`,
}) as Incident

function pageProps(overrides: Partial<Parameters<typeof IncidentsPage>[0]> = {}) {
  return {
    incidents, investigations, isCreateFormOpen: false, onCloseCreateForm: vi.fn(),
    onCreateIncident: vi.fn(), onSelectIncident: vi.fn(), onStartInvestigation: vi.fn(),
    selectedIncident: null, demoEnabled: false, isDemoStarting: false,
    onRunDemo: vi.fn(async () => undefined), onAutoStartDemo: vi.fn(async () => undefined),
    ...overrides,
  }
}

describe('IncidentsPage live ingestion', () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

  it('auto-starts the demo once when the incidents page opens and the demo is enabled', () => {
    const props = pageProps({ demoEnabled: true })
    const { rerender } = render(<IncidentsPage {...props} />)
    rerender(<IncidentsPage {...props} incidents={[...incidents]} />)
    expect(props.onAutoStartDemo).toHaveBeenCalledTimes(1)
  })

  it('auto-starts again after the page is left and reopened', () => {
    const props = pageProps({ demoEnabled: true })
    render(<IncidentsPage {...props} />).unmount()
    render(<IncidentsPage {...props} />)
    expect(props.onAutoStartDemo).toHaveBeenCalledTimes(2)
  })

  it('does not auto-start when the demo is disabled', () => {
    const props = pageProps({ demoEnabled: false })
    render(<IncidentsPage {...props} />)
    expect(props.onAutoStartDemo).not.toHaveBeenCalled()
  })

  it('shows Run demo only when the demo is enabled', () => {
    const { unmount } = render(<IncidentsPage {...pageProps()} />)
    expect(screen.queryByRole('button', { name: 'Run demo' })).toBeNull()
    unmount()
    render(<IncidentsPage {...pageProps({ demoEnabled: true })} />)
    expect(screen.getByRole('button', { name: 'Run demo' })).toBeEnabled()
  })

  it('disables Run demo for 10 seconds after a click and shows "Demo running…"', async () => {
    vi.useFakeTimers()
    const props = pageProps({ demoEnabled: true })
    render(<IncidentsPage {...props} />)
    await act(async () => { screen.getByRole('button', { name: 'Run demo' }).click() })
    expect(props.onRunDemo).toHaveBeenCalledTimes(1)
    const busy = screen.getByRole('button', { name: 'Demo running…' })
    expect(busy).toBeDisabled()
    act(() => { vi.advanceTimersByTime(9_000) })
    expect(screen.getByRole('button', { name: 'Demo running…' })).toBeDisabled()
    act(() => { vi.advanceTimersByTime(1_500) })
    expect(screen.getByRole('button', { name: 'Run demo' })).toBeEnabled()
  })

  it('shows the service and a CloudWatch alarm badge for alarm incidents', () => {
    render(<IncidentsPage {...pageProps({ incidents: [alarm('a1', '2026-11-03T10:00:00Z')] })} />)
    const row = within(screen.getByRole('list')).getByRole('listitem')
    expect(row).toHaveTextContent('checkout-api')
    expect(row).toHaveTextContent('CloudWatch alarm')
  })

  it('shows a Manual badge for manual incidents', () => {
    const manual = { ...incident('m1', 'Manual one', 'LOW', '2026-11-03T10:00:00Z'), source: 'MANUAL', service: null, external_id: null } as Incident
    render(<IncidentsPage {...pageProps({ incidents: [manual] })} />)
    expect(within(screen.getByRole('list')).getByRole('listitem')).toHaveTextContent('Manual')
  })

  it('highlights incidents that were not in the previous list for 4 seconds', () => {
    vi.useFakeTimers()
    const first = [alarm('a1', '2026-11-03T10:00:00Z')]
    const props = pageProps({ incidents: first })
    const { rerender } = render(<IncidentsPage {...props} />)
    expect(document.querySelector('li.is-new')).toBeNull()
    rerender(<IncidentsPage {...props} incidents={[...first, alarm('a2', '2026-11-03T10:05:00Z')]} />)
    const marked = document.querySelectorAll('li.is-new')
    expect(marked).toHaveLength(1)
    expect(marked[0]).toHaveTextContent('Alarm a2')
    act(() => { vi.advanceTimersByTime(4_100) })
    expect(document.querySelector('li.is-new')).toBeNull()
  })

  it('shows detection time relative to now', () => {
    const now = Date.parse('2026-11-03T10:00:12Z')
    vi.spyOn(Date, 'now').mockReturnValue(now)
    const rows = [
      alarm('s', '2026-11-03T10:00:00Z'),
      alarm('m', '2026-11-03T09:55:00Z'),
      alarm('h', '2026-11-03T07:00:00Z'),
    ]
    render(<IncidentsPage {...pageProps({ incidents: rows })} />)
    const text = within(screen.getByRole('list')).getAllByRole('listitem').map((item) => item.textContent).join('|')
    expect(text).toContain('12 s ago')
    expect(text).toContain('5 min ago')
    expect(text).toContain('3 h ago')
  })
})
