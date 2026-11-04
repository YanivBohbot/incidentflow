import { useCurrentFrame, useVideoConfig } from 'remotion'
import { Footage, placeSegments, placedDuration } from '../components/Footage'
import { Card, FRAME, FRAME_H, Stage } from '../components/Stage'
import { TOUR_SPEED, tourEdit, tourScenarios } from '../content/tour'
import { srcToOutFrame } from '../timeline/buildEdit'
import type { Timeline } from '../timeline/types'

export function tourDurationFrames(timeline: Timeline, fps: number): number {
  return placedDuration(placeSegments(tourEdit(timeline).segments, fps))
}

/** Past investigations across domains: the supervisor picks different specialists each time. */
export function Tour({ timeline }: { timeline: Timeline }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const { segments, keys } = tourEdit(timeline)
  const scenarios = tourScenarios(timeline).map((s) => ({
    ...s,
    enter: srcToOutFrame(segments, s.atSrc, fps) ?? 0,
  }))
  const current = scenarios.filter((s) => s.enter <= frame).at(-1)

  return (
    <Stage
      heading="One supervisor, many domains"
      badge={`×${TOUR_SPEED} speed`}
      window={<Footage timeline={timeline} segments={segments} keys={keys} width={FRAME.width} height={FRAME_H} />}
      column={
        <>
          <Card
            enterFrame={0}
            title="Different incident, different specialists"
            body="For each incident the supervisor decides which sub-agents it needs. These are past investigations of other demo scenarios."
          />
          {current && (
            <Card
              key={current.service}
              enterFrame={current.enter}
              title={current.service}
              body={current.title}
              chips={current.agents}
              tone="ok"
            />
          )}
        </>
      }
    />
  )
}
