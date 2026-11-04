import { Footage, placeSegments, placedDuration } from '../components/Footage'
import { Card, FRAME, FRAME_H, Stage } from '../components/Stage'
import { FOCUS } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'

/** From the moment the ticket page is shown to the end of the recording, at real speed. */
export function jiraSegments(timeline: Timeline): Segment[] {
  const shown = timeline.events.find((e) => e.kind === 'page')?.t ?? 0
  return [{ srcFrom: Math.max(0, shown - 0.5), srcTo: timeline.durationS, speed: 1 }]
}

export function jiraDurationFrames(timeline: Timeline, fps: number): number {
  return placedDuration(placeSegments(jiraSegments(timeline), fps))
}

/** The real Jira ticket the approved tool call created. */
export function JiraTicket({ timeline }: { timeline: Timeline }) {
  const key = timeline.investigationId
  return (
    <Stage
      heading={`Created in Jira — ${key}`}
      window={
        <Footage
          timeline={timeline}
          segments={jiraSegments(timeline)}
          keys={[{ atSrc: 0, box: FOCUS.full }]}
          width={FRAME.width}
          height={FRAME_H}
        />
      }
      column={
        <>
          <Card
            enterFrame={6}
            title={`${key} is real`}
            body="Created by the IT Operations agent through Atlassian MCP, only after the operator approved the exact tool call."
            chips={['Atlassian MCP', 'HumanInTheLoopMiddleware']}
            tone="ok"
          />
          <Card
            enterFrame={40}
            title="Written from the evidence"
            body="The summary and description combine the CloudWatch alarms, MongoDB events, the GitHub PR and the runbook."
          />
        </>
      }
    />
  )
}
