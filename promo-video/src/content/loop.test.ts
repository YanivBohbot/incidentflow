import { describe, expect, it } from 'vitest'
import type { Timeline, TimelineEvent } from '../timeline/types'
import { REVIEW_SPEED, loopPlan } from './loop'

const ev = (t: number, kind: TimelineEvent['kind'], label: string = kind): TimelineEvent => ({ t, kind, label })
const take: Timeline = {
  recording: 'take.webm',
  durationS: 100,
  investigationId: 'x',
  masks: [],
  events: [
    ev(8, 'click', 'Launch investigation'),
    ev(15, 'trace_step'),
    ev(60, 'trace_step'),
    ev(70, 'hitl_pause'),
    ev(80, 'typing_start'),
    ev(85, 'typing_end'),
    ev(86, 'approved'),
    ev(99, 'completed'),
  ],
}
const tour: Timeline = { recording: 'tour.webm', durationS: 36, investigationId: '', masks: [], events: [] }

describe('loopPlan', () => {
  const plan = loopPlan(tour, take)

  it('runs the trace from launch to the HITL pause fast', () => {
    expect(plan.trace[0].srcFrom).toBe(8)
    expect(plan.trace.at(-1)!.srcTo).toBeCloseTo(69.2)
    expect(Math.min(...plan.trace.map((s) => s.speed))).toBeGreaterThanOrEqual(2)
  })

  it('shows the whole human review, from the pause to the approval, at a readable speed', () => {
    expect(plan.review[0].srcFrom).toBeCloseTo(69.2)
    expect(plan.review.at(-1)!.srcTo).toBe(88)
    for (const s of plan.review) expect(s.speed).toBe(REVIEW_SPEED)
  })

  it('ends on the Jira ticket', () => {
    expect(plan.jiraFrames).toBeGreaterThan(0)
  })
})
