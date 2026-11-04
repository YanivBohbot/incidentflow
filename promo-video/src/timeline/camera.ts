import type { Box, Timeline } from './types'

/**
 * Regions of the 1920×1080 recording worth filling the frame with (16:9 each). Measured on the
 * IncidentFlow layout at 1920 px: the trace column sits on the right of the Investigations page,
 * the review panel on the left of the Approvals page.
 */
export const FOCUS = {
  full: { x: 0, y: 0, width: 1920, height: 1080 },
  trace: { x: 760, y: 420, width: 1150, height: 647 },
  reviewTop: { x: 330, y: 0, width: 1040, height: 585 },
  reviewBottom: { x: 330, y: 470, width: 1040, height: 585 },
  report: { x: 795, y: 10, width: 1040, height: 585 },
} satisfies Record<string, Box>

export type CameraKey = { atSrc: number; box: Box }

/** Where the camera looks, from the moments of the take. */
export function cameraKeyframes(timeline: Timeline): CameraKey[] {
  const first = (kind: string, label?: string) =>
    [...timeline.events]
      .sort((a, b) => a.t - b.t)
      .find((e) => e.kind === kind && (!label || e.label === label))
  const keys: CameraKey[] = [{ atSrc: 0, box: FOCUS.full }]
  const launch = first('click', 'Launch investigation')
  const pause = first('hitl_pause')
  const typing = first('typing_start')
  const approved = first('approved')
  if (launch) keys.push({ atSrc: launch.t + 1.5, box: FOCUS.trace })
  if (pause) keys.push({ atSrc: pause.t + 1, box: FOCUS.reviewTop })
  if (typing) keys.push({ atSrc: typing.t, box: FOCUS.reviewBottom })
  if (approved) keys.push({ atSrc: approved.t + 2.5, box: FOCUS.trace })
  return keys.filter((k, i) => i === 0 || k.atSrc > keys[i - 1].atSrc)
}

/** Linear blend of two boxes, p in [0, 1]. */
export function lerpBox(a: Box, b: Box, p: number): Box {
  const mix = (x: number, y: number) => x + (y - x) * p
  return { x: mix(a.x, b.x), y: mix(a.y, b.y), width: mix(a.width, b.width), height: mix(a.height, b.height) }
}
