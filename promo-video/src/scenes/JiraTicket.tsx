import { Img, interpolate, staticFile, useCurrentFrame } from 'remotion'
import { Card, FRAME, FRAME_H, Stage } from '../components/Stage'
import { lerpBox } from '../timeline/camera'
import type { Box } from '../timeline/types'

/** Screenshot of the real ticket page, taken by the owner (Google sign-in blocks automation). */
export const JIRA_SHOT = { file: 'jira.png', width: 1504, height: 921, key: 'SAM1-23' }
export const JIRA_FRAMES = 11 * 30

const SHOTS: { at: number; box: Box }[] = [
  { at: 0, box: { x: 0, y: 0, width: 1504, height: 846 } },
  { at: 75, box: { x: 320, y: 50, width: 760, height: 428 } },
  { at: 200, box: { x: 790, y: 60, width: 714, height: 402 } },
]
/** Personal details on the page: reporter name and avatars. */
const MASKS: Box[] = [
  { x: 1252, y: 548, width: 130, height: 32 },
  { x: 1472, y: 4, width: 32, height: 32 },
  { x: 348, y: 866, width: 32, height: 32 },
]
const MOVE = 30

function viewAt(frame: number): Box {
  const index = SHOTS.filter((s) => s.at <= frame).length - 1
  const target = SHOTS[Math.max(0, index)]
  const previous = SHOTS[Math.max(0, index - 1)]
  const p = interpolate(frame, [target.at, target.at + MOVE], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: (t) => t * t * (3 - 2 * t),
  })
  return lerpBox(previous.box, target.box, p)
}

/** The real Jira ticket the approved tool call created. */
export function JiraTicket() {
  const frame = useCurrentFrame()
  const view = viewAt(frame)
  const zoom = FRAME.width / view.width
  return (
    <Stage
      heading={`Created in Jira — ${JIRA_SHOT.key}`}
      windowTitle={`Jira — ${JIRA_SHOT.key}`}
      window={
        <div style={{ position: 'relative', width: FRAME.width, height: FRAME_H, overflow: 'hidden', background: '#fff' }}>
          <div
            style={{
              position: 'absolute',
              width: JIRA_SHOT.width,
              height: JIRA_SHOT.height,
              transformOrigin: 'top left',
              transform: `translate(${-view.x * zoom}px, ${-view.y * zoom}px) scale(${zoom})`,
            }}
          >
            <Img src={staticFile(JIRA_SHOT.file)} style={{ width: JIRA_SHOT.width, height: JIRA_SHOT.height }} />
            {MASKS.map((m, i) => (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: m.x,
                  top: m.y,
                  width: m.width,
                  height: m.height,
                  backdropFilter: 'blur(8px)',
                  background: 'rgb(203,213,225)',
                  borderRadius: 6,
                }}
              />
            ))}
          </div>
        </div>
      }
      column={
        <>
          <Card
            enterFrame={10}
            title={`${JIRA_SHOT.key} is real`}
            body="Created by the IT Operations agent through Atlassian MCP, only after the operator approved the exact tool call."
            chips={['Atlassian MCP', 'HumanInTheLoopMiddleware']}
            tone="ok"
          />
          <Card
            enterFrame={80}
            title="Written from the evidence"
            body="CloudWatch alarms and logs, MongoDB events, the GitHub PR and the runbook — combined into one actionable ticket."
          />
          <Card
            enterFrame={205}
            title="Ready for on-call"
            body="Task · High priority · To Do — in the team's project, no copy-paste needed."
          />
        </>
      }
    />
  )
}
