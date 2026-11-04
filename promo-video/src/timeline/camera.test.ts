import { describe, expect, it } from 'vitest'
import { FOCUS, cameraKeyframes, keysForSegments } from './camera'
import type { Timeline, TimelineEvent } from './types'

const ev = (t: number, kind: TimelineEvent['kind'], label: string = kind): TimelineEvent => ({ t, kind, label })
const timeline = (events: TimelineEvent[]): Timeline => ({
  recording: 'x', durationS: 100, investigationId: 'x', events, masks: [],
})

describe('cameraKeyframes', () => {
  const full = timeline([
    ev(4, 'page', 'Incidents'),
    ev(9, 'click', 'Launch investigation'),
    ev(50, 'hitl_pause'),
    ev(52, 'page', 'Review draft'),
    ev(56, 'typing_start'),
    ev(60, 'approved'),
    ev(70, 'hitl_pause'),
    ev(80, 'completed'),
  ])

  it('starts on the full app, then follows trace, request, draft, typing, and back to the trace', () => {
    expect(cameraKeyframes(full).map((k) => k.box)).toEqual([
      FOCUS.full,
      FOCUS.trace,
      FOCUS.reviewTop,
      FOCUS.reviewDraft,
      FOCUS.reviewBottom,
      FOCUS.trace,
    ])
  })

  it('frames the review panel at the pause itself, when the app switches to it', () => {
    expect(cameraKeyframes(full).find((k) => k.box === FOCUS.reviewTop)!.atSrc).toBeCloseTo(49.2)
  })

  it('uses only the first HITL pause', () => {
    expect(cameraKeyframes(full).filter((k) => k.box === FOCUS.reviewTop)).toHaveLength(1)
  })

  it('keyframes are in time order and every focus box keeps the 16:9 frame', () => {
    const keys = cameraKeyframes(full)
    keys.forEach((k, i) => i && expect(k.atSrc).toBeGreaterThan(keys[i - 1].atSrc))
    for (const box of Object.values(FOCUS)) expect(box.width / box.height).toBeCloseTo(16 / 9, 1)
  })

  it('stays on the full app when nothing was launched (rehearsal)', () => {
    expect(cameraKeyframes(timeline([ev(4, 'page', 'Incidents')])).map((k) => k.box)).toEqual([FOCUS.full])
  })
})

describe('keysForSegments', () => {
  const keys = [
    { atSrc: 0, box: FOCUS.full },
    { atSrc: 10, box: FOCUS.trace },
    { atSrc: 51, box: FOCUS.reviewTop },
    { atSrc: 56, box: FOCUS.reviewBottom },
    { atSrc: 92, box: FOCUS.trace },
  ]
  const review = [{ srcFrom: 50, srcTo: 90, speed: 1 }]

  it('starts on the last key before the excerpt and drops keys after it', () => {
    const placed = keysForSegments(keys, review, 30)
    expect(placed.map((k) => k.box)).toEqual([FOCUS.trace, FOCUS.reviewTop, FOCUS.reviewBottom])
    expect(placed.map((k) => k.at)).toEqual([0, 30, 180])
  })
})
