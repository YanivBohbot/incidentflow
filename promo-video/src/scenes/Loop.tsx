import { AbsoluteFill, Series } from 'remotion'
import { Footage, placeSegments, placedDuration } from '../components/Footage'
import { tourEdit } from '../content/tour'
import { buildEdit } from '../timeline/buildEdit'
import { cameraKeyframes } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'

const LOOP_TOUR_SPEED = 4
const LOOP_TAKE_SPEED_UP = 2

/** Segments restricted to [from, to] of the source, each sped up by `factor`. */
export function sliceSegments(segments: Segment[], from: number, to: number, factor: number): Segment[] {
  return segments
    .map((s) => ({ srcFrom: Math.max(s.srcFrom, from), srcTo: Math.min(s.srcTo, to), speed: s.speed * factor }))
    .filter((s) => s.srcTo > s.srcFrom)
}

function loopParts(tour: Timeline, take: Timeline) {
  const tourSegments = tourEdit(tour).segments.map((s) => ({ ...s, speed: LOOP_TOUR_SPEED }))
  const launch = take.events.find((e) => e.kind === 'click' && e.label === 'Launch investigation')?.t ?? 0
  const approved = take.events.find((e) => e.kind === 'approved')?.t ?? take.durationS
  const takeSegments = sliceSegments(buildEdit(take), launch, approved + 2, LOOP_TAKE_SPEED_UP)
  return { tourSegments, takeSegments }
}

export function loopDurationFrames(tour: Timeline, take: Timeline, fps: number) {
  const { tourSegments, takeSegments } = loopParts(tour, take)
  return {
    tour: placedDuration(placeSegments(tourSegments, fps)),
    take: placedDuration(placeSegments(takeSegments, fps)),
  }
}

/** README loop: the app only — the scenario tour, then the live trace up to the approval. */
export function Loop({ tour, take, fps }: { tour: Timeline; take: Timeline; fps: number }) {
  const { tourSegments, takeSegments } = loopParts(tour, take)
  const durations = loopDurationFrames(tour, take, fps)
  return (
    <AbsoluteFill style={{ background: '#f5f7fb' }}>
      <Series>
        <Series.Sequence durationInFrames={durations.tour}>
          <Footage timeline={tour} segments={tourSegments} keys={tourEdit(tour).keys} width={1920} height={1080} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={durations.take}>
          <Footage timeline={take} segments={takeSegments} keys={cameraKeyframes(take)} width={1920} height={1080} />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  )
}
