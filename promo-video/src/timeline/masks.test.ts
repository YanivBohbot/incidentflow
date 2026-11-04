import { describe, expect, it } from 'vitest'
import { activeMasks } from './masks'
import type { Timeline } from './types'

const box = { x: 1, y: 2, width: 3, height: 4 }
const timeline: Timeline = {
  recording: 'x',
  durationS: 100,
  investigationId: 'x',
  events: [{ t: 74.3, kind: 'page', label: 'Approvals' }],
  masks: [{ from: 72.4, to: 74.0 + 2, box }],
}

describe('activeMasks', () => {
  it('shows a mask inside its time window', () => {
    expect(activeMasks(timeline, 73)).toEqual([timeline.masks[0]])
  })
  it('drops a mask once the page it was measured on has changed', () => {
    expect(activeMasks(timeline, 74.5)).toEqual([])
  })
  it('keeps a mask when the event is a scroll on the same page, not a navigation', () => {
    const scrolled: Timeline = {
      ...timeline,
      events: [{ t: 78.3, kind: 'page', label: 'Review draft' }],
      masks: [{ from: 74.5, to: 78.8, box }],
    }
    expect(activeMasks(scrolled, 78.5)).toEqual(scrolled.masks)
  })

  it('covers the review panel from up to 1.5 s before the detected pause (polling lag)', () => {
    const paused: Timeline = {
      ...timeline,
      events: [
        { t: 73.8, kind: 'hitl_pause', label: 'Paused' },
        { t: 74.3, kind: 'page', label: 'Approvals' },
      ],
      masks: [
        { from: 72.4, to: 76, box },
        { from: 74.2, to: 78.8, box: { ...box, x: 400 } },
      ],
    }
    // While the switch time is uncertain, the trace masks stay too (both pages are covered)…
    expect(activeMasks(paused, 72.5)).toEqual([
      { from: 72.4, to: 76, box },
      { from: 72.3, to: 78.8, box: { ...box, x: 400 } },
    ])
    // …and they stop at the detected pause.
    expect(activeMasks(paused, 74)).toEqual([{ from: 72.3, to: 78.8, box: { ...box, x: 400 } }])
    // …and keeps covering it after the script marks the Approvals page it was measured on.
    expect(activeMasks(paused, 76)).toEqual([{ from: 72.3, to: 78.8, box: { ...box, x: 400 } }])
  })

  it('ignores masks outside their window', () => {
    expect(activeMasks(timeline, 80)).toEqual([])
  })
})
