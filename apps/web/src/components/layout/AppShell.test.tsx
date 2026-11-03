import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

function renderShell(pendingApprovalCount: number, activePage: 'overview' | 'approvals' = 'overview') {
  const onPageChange = vi.fn()
  render(
    <AppShell activePage={activePage} onCreateIncident={vi.fn()} onPageChange={onPageChange} pendingApprovalCount={pendingApprovalCount} statusMessage="ok">
      <p>page</p>
    </AppShell>,
  )
  return { onPageChange }
}

describe('AppShell approval alert', () => {
  it('shows a badge and a banner that opens Approvals when a decision is waiting', async () => {
    const { onPageChange } = renderShell(2)

    expect(screen.getByLabelText('2 pending')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('2 decisions are waiting for you.')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Review now' }))
    expect(onPageChange).toHaveBeenCalledWith('approvals')
  })

  it('shows no alert when nothing is pending, and no banner on the Approvals page itself', () => {
    renderShell(0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/pending/)).not.toBeInTheDocument()
  })

  it('keeps the badge but hides the banner on the Approvals page', () => {
    renderShell(1, 'approvals')
    expect(screen.getByLabelText('1 pending')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
