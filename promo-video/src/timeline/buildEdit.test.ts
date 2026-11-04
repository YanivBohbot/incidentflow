import { describe, expect, it } from 'vitest'
import { buildEdit, srcToOutFrame } from './buildEdit'
import type { Timeline, TimelineEvent } from './types'

const timeline = (events: TimelineEvent[], durationS: number): Timeline => ({
  recording: 'take.webm',
  durationS,
  investigationId: 'x',
  events,
  masks: [],
})
const ev = (t: number, kind: TimelineEvent['kind'] = 'trace_step'): TimelineEvent => ({
  t,
  kind,
  label: kind,
})

describe('buildEdit', () => {
  it('speeds up idle gaps longer than maxIdle', () => {
    const segments = buildEdit(timeline([ev(0), ev(1), ev(20), ev(21)], 21))
    expect(segments).toEqual([
      { srcFrom: 0, srcTo: 1, speed: 1 },
      { srcFrom: 1, srcTo: 20, speed: 4 },
      { srcFrom: 20, srcTo: 21, speed: 1 },
    ])
  })

  it('never speeds up typing or the HITL moment', () => {
    const segments = buildEdit(
      timeline([ev(0), ev(10, 'hitl_pause'), ev(12, 'typing_start'), ev(30, 'typing_end')], 40),
    )
    for (const s of segments) {
      if (s.srcFrom < 30 && s.srcTo > 12) expect(s.speed).toBe(1)
      if (s.srcFrom < 11.5 && s.srcTo > 8.5) expect(s.speed).toBe(1)
    }
  })

  it('returns contiguous, monotonic segments covering the whole recording', () => {
    const segments = buildEdit(
      timeline([ev(3), ev(9, 'hitl_pause'), ev(10, 'typing_start'), ev(14, 'typing_end'), ev(50)], 60),
    )
    expect(segments[0].srcFrom).toBe(0)
    expect(segments.at(-1)!.srcTo).toBe(60)
    segments.forEach((s, i) => {
      expect(s.srcFrom).toBeLessThan(s.srcTo)
      if (i > 0) expect(s.srcFrom).toBe(segments[i - 1].srcTo)
    })
  })

  it('tolerates unsorted and duplicate event times', () => {
    const segments = buildEdit(timeline([ev(20), ev(1), ev(1), ev(0), ev(21)], 21))
    expect(segments).toEqual(buildEdit(timeline([ev(0), ev(1), ev(20), ev(21)], 21)))
  })
})

describe('srcToOutFrame', () => {
  it('maps source time through speed-ups', () => {
    const segments = buildEdit(timeline([ev(0), ev(1), ev(20), ev(21)], 21))
    expect(srcToOutFrame(segments, 20, 30)).toBe(Math.round((1 + 19 / 4) * 30))
    expect(srcToOutFrame(segments, 0.5, 30)).toBe(15)
    expect(srcToOutFrame(segments, 99, 30)).toBeNull()
  })
})
