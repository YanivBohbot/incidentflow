import type { Segment, Timeline } from './types'

type Options = { maxIdleS?: number; waitSpeed?: number }

const PROTECT_AROUND_S = 1.5

/** Spans that must play at real speed: the operator typing, and the pause/approve moments. */
function protectedSpans(timeline: Timeline): [number, number][] {
  const spans: [number, number][] = []
  const starts = timeline.events.filter((e) => e.kind === 'typing_start').map((e) => e.t)
  const ends = timeline.events.filter((e) => e.kind === 'typing_end').map((e) => e.t)
  starts.forEach((start) => {
    const end = ends.filter((t) => t >= start).sort((a, b) => a - b)[0] ?? start
    spans.push([start, end])
  })
  for (const e of timeline.events) {
    if (e.kind === 'hitl_pause' || e.kind === 'approved') {
      spans.push([e.t - PROTECT_AROUND_S, e.t + PROTECT_AROUND_S])
    }
  }
  // The human review is the point of the demo: keep it readable from the pause to the approval.
  const pause = Math.min(...timeline.events.filter((e) => e.kind === 'hitl_pause').map((e) => e.t))
  const approved = timeline.events.find((e) => e.kind === 'approved' && e.t > pause)
  if (approved) spans.push([pause - PROTECT_AROUND_S, approved.t + PROTECT_AROUND_S])
  return spans
}

/**
 * Decide how each part of the recording plays: gaps between events longer than `maxIdleS` are
 * sped up by `waitSpeed`, except protected spans. Segments are contiguous and cover
 * [0, durationS].
 */
export function buildEdit(timeline: Timeline, opts: Options = {}): Segment[] {
  const maxIdleS = opts.maxIdleS ?? 2.5
  const waitSpeed = opts.waitSpeed ?? 4
  const end = timeline.durationS
  const spans = protectedSpans(timeline)

  const points = [...new Set([0, end, ...timeline.events.map((e) => e.t)])]
    .filter((t) => t >= 0 && t <= end)
    .sort((a, b) => a - b)

  // Cut points also at protected span edges so a gap can be split around them.
  const cuts = [
    ...new Set([...points, ...spans.flat().map((t) => Math.min(Math.max(t, 0), end))]),
  ].sort((a, b) => a - b)

  const isProtected = (from: number, to: number) =>
    spans.some(([a, b]) => from < b && to > a)
  const gapFor = (t: number) => {
    const next = points.find((p) => p > t) ?? end
    const prev = [...points].reverse().find((p) => p <= t) ?? 0
    return next - prev
  }

  const raw: Segment[] = []
  for (let i = 0; i < cuts.length - 1; i++) {
    const [from, to] = [cuts[i], cuts[i + 1]]
    if (to <= from) continue
    const fast = gapFor(from) > maxIdleS && !isProtected(from, to)
    raw.push({ srcFrom: from, srcTo: to, speed: fast ? waitSpeed : 1 })
  }

  const merged: Segment[] = []
  for (const s of raw) {
    const last = merged.at(-1)
    if (last && last.speed === s.speed && last.srcTo === s.srcFrom) last.srcTo = s.srcTo
    else merged.push({ ...s })
  }
  return merged
}

/** Output frame at which source time `srcT` is shown, or null when it is outside the edit. */
export function srcToOutFrame(segments: Segment[], srcT: number, fps: number): number | null {
  let outS = 0
  for (const s of segments) {
    if (srcT >= s.srcFrom && srcT <= s.srcTo) {
      return Math.round((outS + (srcT - s.srcFrom) / s.speed) * fps)
    }
    outS += (s.srcTo - s.srcFrom) / s.speed
  }
  return null
}

/** Total output duration in frames. */
export function editDurationFrames(segments: Segment[], fps: number): number {
  return Math.round(segments.reduce((sum, s) => sum + (s.srcTo - s.srcFrom) / s.speed, 0) * fps)
}
