import type { Timeline } from './types'

/** Navigation between app pages; other `page` events (e.g. "Review draft") are scrolls. */
const NAVIGATION = new Set(['Overview', 'Incidents', 'Investigations', 'Approvals'])
const PAUSE_SETTLE_S = 1.5
/** The app shows the review panel up to ~1 s before the script's polling detects the pause. */
const PAUSE_LEAD_S = 1.5
/** The filming scripts start each mask up to 0.3 s before the moment it was measured. */
const MEASURE_LEAD_S = 0.3

/**
 * Masks visible at source time `srcT`.
 *
 * - Boxes are measured on one page: a mask stops at the first navigation (or detected HITL pause,
 *   when the app has switched to the review panel by itself) that happens after it was measured.
 * - At the HITL pause the app shows the review panel before the script measures it, so masks
 *   measured within PAUSE_SETTLE_S after the pause are shown from the pause on.
 */
export function activeMasks(timeline: Timeline, srcT: number): Timeline['masks'] {
  const pauses = timeline.events.filter((e) => e.kind === 'hitl_pause').map((e) => e.t)
  const pause = pauses.length > 0 ? Math.min(...pauses) : Number.POSITIVE_INFINITY
  const changes = timeline.events
    .filter((e) => e.kind === 'page' && NAVIGATION.has(e.label))
    .map((e) => e.t)
    .concat(Number.isFinite(pause) ? [pause] : [])

  return timeline.masks
    .filter((m) => !changes.some((t) => t > m.from + MEASURE_LEAD_S && t <= srcT))
    .map((m) =>
      m.from > pause && m.from <= pause + PAUSE_SETTLE_S ? { ...m, from: pause - PAUSE_LEAD_S } : m,
    )
    .filter((m) => srcT >= m.from && srcT <= m.to)
}
