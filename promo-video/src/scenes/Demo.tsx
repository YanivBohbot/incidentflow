import { useCurrentFrame, useVideoConfig } from 'remotion'
import { Footage, placeSegments, placedDuration, sourceAt } from '../components/Footage'
import { Card, FRAME, FRAME_H, Stage } from '../components/Stage'
import { calloutsFor } from '../content/callouts'
import { buildEdit, srcToOutFrame } from '../timeline/buildEdit'
import { cameraKeyframes } from '../timeline/camera'
import type { Timeline } from '../timeline/types'

export function demoDurationFrames(timeline: Timeline, fps: number): number {
  return placedDuration(placeSegments(buildEdit(timeline), fps))
}

function chapter(timeline: Timeline, srcT: number): string {
  const passed = (kind: string, label?: string) =>
    timeline.events.some((e) => e.kind === kind && (!label || e.label === label) && e.t <= srcT)
  if (passed('approved')) return 'Approved — the workflow resumes'
  if (passed('hitl_pause')) return 'Human approval'
  if (passed('click', 'Launch investigation')) return 'Live multi-agent trace'
  return 'Incident dashboard'
}

/** The live take: the real app, zoomed where it matters, explanations alongside. */
export function Demo({ timeline }: { timeline: Timeline }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const segments = buildEdit(timeline)
  const { current, srcNow } = sourceAt(placeSegments(segments, fps), frame, fps)

  const callouts = calloutsFor(timeline)
    .map((callout) => ({ callout, enter: srcToOutFrame(segments, callout.atSrc, fps) ?? 0 }))
    .filter(({ callout, enter }) => frame >= enter && frame < enter + callout.holdS * fps)
    .slice(-3)

  return (
    <Stage
      heading={chapter(timeline, srcNow)}
      badge={current.speed > 1 ? `×${current.speed} speed` : undefined}
      window={
        <Footage
          timeline={timeline}
          segments={segments}
          keys={cameraKeyframes(timeline)}
          width={FRAME.width}
          height={FRAME_H}
        />
      }
      column={callouts.map(({ callout, enter }) => (
        <Card key={`${callout.title}-${callout.atSrc}`} enterFrame={enter} {...callout} />
      ))}
    />
  )
}
