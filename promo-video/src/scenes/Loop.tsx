import { AbsoluteFill, Series, useCurrentFrame } from 'remotion'
import { Footage, placeSegments, placedDuration } from '../components/Footage'
import { loopPlan } from '../content/loop'
import { tourEdit } from '../content/tour'
import { cameraKeyframes } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'
import { JiraShot } from './JiraTicket'

const frames = (segments: Segment[], fps: number) => placedDuration(placeSegments(segments, fps))

export function loopDurationFrames(tour: Timeline, take: Timeline, fps: number): number {
  const plan = loopPlan(tour, take)
  return frames(plan.tour, fps) + frames(plan.trace, fps) + frames(plan.review, fps) + plan.jiraFrames
}

function JiraPart() {
  return <JiraShot width={1920} height={1080} frame={useCurrentFrame()} />
}

/** README loop, app only: scenario tour → live trace → human approval → the Jira ticket. */
export function Loop({ tour, take, fps }: { tour: Timeline; take: Timeline; fps: number }) {
  const plan = loopPlan(tour, take)
  const keys = cameraKeyframes(take)
  return (
    <AbsoluteFill style={{ background: '#f5f7fb' }}>
      <Series>
        <Series.Sequence durationInFrames={frames(plan.tour, fps)}>
          <Footage timeline={tour} segments={plan.tour} keys={tourEdit(tour).keys} width={1920} height={1080} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={frames(plan.trace, fps)}>
          <Footage timeline={take} segments={plan.trace} keys={keys} width={1920} height={1080} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={frames(plan.review, fps)}>
          <Footage timeline={take} segments={plan.review} keys={keys} width={1920} height={1080} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={plan.jiraFrames}>
          <JiraPart />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  )
}
