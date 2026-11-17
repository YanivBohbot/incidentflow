import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Incident, Investigation } from '../../api'
import { ConfirmedLessonForm } from './ConfirmedLessonForm'

const incident = { id: 'inc', service: 'inventory-service' } as Incident
const investigation = {
  id: 'inv',
  report: {
    summary: 's', confidence: 0.8,
    root_cause: 'Unbounded in-memory stock cache since release 2.4.1.',
    proposed_actions: ['Add a size limit and eviction to the cache'],
  },
} as unknown as Investigation

afterEach(cleanup)

describe('ConfirmedLessonForm', () => {
  it('prefills the service and root cause from the report, but not the resolution', () => {
    render(<ConfirmedLessonForm incident={incident} investigation={investigation} onConfirm={vi.fn()} />)

    expect(screen.getByLabelText('Affected service')).toHaveValue('inventory-service')
    expect(screen.getByLabelText('Confirmed root cause')).toHaveValue('Unbounded in-memory stock cache since release 2.4.1.')
    const resolution = screen.getByLabelText('Validated resolution')
    expect(resolution).toHaveValue('')
    expect(resolution).toHaveAttribute('placeholder', 'What actually fixed it, e.g. Add a size limit and eviction to the cache')
  })

  it('leaves the fields empty for reports without a root cause', () => {
    render(<ConfirmedLessonForm investigation={{ ...investigation, report: null }} onConfirm={vi.fn()} />)

    expect(screen.getByLabelText('Affected service')).toHaveValue('')
    expect(screen.getByLabelText('Confirmed root cause')).toHaveValue('')
  })
})
