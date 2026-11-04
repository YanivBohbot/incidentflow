import { srcToOutFrame } from './buildEdit'
import type { Box, Segment, Timeline } from './types'

/**
 * Regions of the 1920×1080 recording worth filling the frame with (16:9 each). Measured on the
 * IncidentFlow layout at 1920 px: the trace column sits on the right of the Investigations page,
 * the review panel on the left of the Approvals page.
 */
export const FOCUS = {
  full: { x: 0, y: 0, width: 1920, height: 1080 },
  trace: { x: 760, y: 420, width: 1150, height: 647 },
  // The review panel fits the viewport: request + Jira target, then the draft, then the decision.
  reviewTop: { x: 330, y: 50, width: 1100, height: 619 },
  reviewDraft: { x: 330, y: 290, width: 1100, height: 619 },
  reviewBottom: { x: 330, y: 440, width: 1100, height: 619 },
  report: { x: 795, y: 10, width: 1040, height: 585 },
} satisfies Record<string, Box>

export type CameraKey = { atSrc: number; box: Box }

/** The app switches to the review panel up to ~1 s before the script's 1 s polling sees the pause. */
export const PAUSE_CAMERA_LEAD_S = 0.8

/** Where the camera looks, from the moments of the take. */
export function cameraKeyframes(timeline: Timeline): CameraKey[] {
  const first = (kind: string, label?: string) =>
    [...timeline.events]
      .sort((a, b) => a.t - b.t)
      .find((e) => e.kind === kind && (!label || e.label === label))
  const keys: CameraKey[] = [{ atSrc: 0, box: FOCUS.full }]
  const launch = first('click', 'Launch investigation')
  const pause = first('hitl_pause')
  const draft = first('page', 'Review draft')
  const typing = first('typing_start')
  const approved = first('approved')
  if (launch) keys.push({ atSrc: launch.t + 1.5, box: FOCUS.trace })
  if (pause) keys.push({ atSrc: pause.t - PAUSE_CAMERA_LEAD_S, box: FOCUS.reviewTop })
  if (draft) keys.push({ atSrc: draft.t, box: FOCUS.reviewDraft })
  if (typing) keys.push({ atSrc: typing.t - 0.8, box: FOCUS.reviewBottom })
  if (approved) keys.push({ atSrc: approved.t + 2.5, box: FOCUS.trace })
  return keys.filter((k, i) => i === 0 || k.atSrc > keys[i - 1].atSrc)
}

/** Linear blend of two boxes, p in [0, 1]. */
export function lerpBox(a: Box, b: Box, p: number): Box {
  const mix = (x: number, y: number) => x + (y - x) * p
  return { x: mix(a.x, b.x), y: mix(a.y, b.y), width: mix(a.width, b.width), height: mix(a.height, b.height) }
}

/**
 * Camera keys placed on the output frames of an excerpt. The excerpt opens on the last key set
 * before it; keys after it are dropped.
 */
export function keysForSegments(
  keys: CameraKey[],
  segments: Segment[],
  fps: number,
): (CameraKey & { at: number })[] {
  const start = segments[0]?.srcFrom ?? 0
  const end = segments.at(-1)?.srcTo ?? 0
  const before = keys.filter((k) => k.atSrc <= start).at(-1)
  const inside = keys
    .filter((k) => k.atSrc > start && k.atSrc <= end)
    .map((k) => ({ ...k, at: srcToOutFrame(segments, k.atSrc, fps) ?? 0 }))
  return [...(before ? [{ ...before, at: 0 }] : []), ...inside]
}
