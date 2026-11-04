import { buildEdit } from '../timeline/buildEdit'
import { PAUSE_CAMERA_LEAD_S } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'
import { tourEdit } from './tour'

/** README loop: fast tour, fast trace, readable human review, then the Jira ticket. */
export const LOOP_TOUR_SPEED = 6
export const LOOP_TRACE_SPEED_UP = 2
export const REVIEW_SPEED = 1.25
export const LOOP_JIRA_FRAMES = 6 * 30

/** Segments restricted to [from, to] of the source, with `speed` replacing or scaling theirs. */
function slice(segments: Segment[], from: number, to: number, speed: (s: Segment) => number): Segment[] {
  return segments
    .map((s) => ({ srcFrom: Math.max(s.srcFrom, from), srcTo: Math.min(s.srcTo, to), speed: speed(s) }))
    .filter((s) => s.srcTo > s.srcFrom)
}

export function loopPlan(tour: Timeline, take: Timeline) {
  const first = (kind: string, label?: string) =>
    [...take.events].sort((a, b) => a.t - b.t).find((e) => e.kind === kind && (!label || e.label === label))
  const launch = first('click', 'Launch investigation')?.t ?? 0
  const pause = (first('hitl_pause')?.t ?? take.durationS) - PAUSE_CAMERA_LEAD_S
  const approved = first('approved')?.t ?? pause
  const edit = buildEdit(take)
  return {
    tour: tourEdit(tour).segments.map((s) => ({ ...s, speed: LOOP_TOUR_SPEED })),
    trace: slice(edit, launch, pause, (s) => Math.max(2, s.speed * LOOP_TRACE_SPEED_UP)),
    review: slice(edit, pause, Math.min(take.durationS, approved + 2), () => REVIEW_SPEED),
    jiraFrames: LOOP_JIRA_FRAMES,
  }
}
