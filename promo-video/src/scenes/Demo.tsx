import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion'
import { Chip } from '../components/ui'
import { type Callout, calloutsFor } from '../content/callouts'
import { buildEdit, srcToOutFrame } from '../timeline/buildEdit'
import { cameraKeyframes, lerpBox } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'
import { theme } from '../theme'

const SRC_W = 1920
const FRAME = { x: 60, y: 120, width: 1300 }
const FRAME_H = Math.round((1080 * FRAME.width) / SRC_W)
const CAMERA_MOVE_FRAMES = 24
const TITLE_BAR = 36
const COLUMN = { x: FRAME.x + FRAME.width + 40, width: 1920 - (FRAME.x + FRAME.width + 40) - 50 }

/** Output frames of each edit segment, laid end to end. */
function segmentFrames(segments: Segment[], fps: number) {
  let at = 0
  return segments.map((s) => {
    const duration = Math.max(1, Math.round(((s.srcTo - s.srcFrom) / s.speed) * fps))
    const item = { ...s, from: at, duration }
    at += duration
    return item
  })
}

export function demoDurationFrames(timeline: Timeline, fps: number): number {
  return segmentFrames(buildEdit(timeline), fps).reduce((sum, s) => sum + s.duration, 0)
}

function chapter(timeline: Timeline, srcT: number): string {
  const passed = (kind: string, label?: string) =>
    timeline.events.some((e) => e.kind === kind && (!label || e.label === label) && e.t <= srcT)
  if (passed('approved')) return 'Approved — the workflow resumes'
  if (passed('hitl_pause')) return 'Human approval'
  if (passed('click', 'Launch investigation')) return 'Live multi-agent trace'
  return 'Incident dashboard'
}

function CalloutCard({ callout, enterFrame }: { callout: Callout; enterFrame: number }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const p = spring({ frame: frame - enterFrame, fps, config: { damping: 18 } })
  const color = callout.tone === 'warn' ? theme.warn : callout.tone === 'ok' ? theme.ok : theme.accent
  return (
    <div
      style={{
        opacity: p,
        transform: `translateX(${interpolate(p, [0, 1], [40, 0])}px)`,
        background: theme.panel,
        border: `1.5px solid ${color}66`,
        borderLeft: `6px solid ${color}`,
        borderRadius: 14,
        padding: '18px 20px',
        marginBottom: 16,
      }}
    >
      <div style={{ fontSize: 28, fontWeight: 800, color: theme.text }}>{callout.title}</div>
      <div style={{ fontSize: 21, color: theme.dim, marginTop: 8, lineHeight: 1.4 }}>{callout.body}</div>
      {callout.chips.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
          {callout.chips.map((chip) => (
            <Chip key={chip} color={color} style={{ fontSize: 16, padding: '4px 10px' }}>
              {chip}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}

/** The real recording, edited by the timeline, with explanations alongside. */
export function Demo({ timeline }: { timeline: Timeline }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const segments = buildEdit(timeline)
  const placed = segmentFrames(segments, fps)
  const current = placed.find((s) => frame >= s.from && frame < s.from + s.duration) ?? placed.at(-1)!
  const srcNow = current.srcFrom + ((frame - current.from) / fps) * current.speed

  const callouts = calloutsFor(timeline)
    .map((callout) => ({ callout, enter: srcToOutFrame(segments, callout.atSrc, fps) ?? 0 }))
    .filter(({ callout, enter }) => frame >= enter && frame < enter + callout.holdS * fps)
    .slice(-3)

  const masks = timeline.masks.filter((m) => srcNow >= m.from && srcNow <= m.to)

  const keys = cameraKeyframes(timeline).map((k) => ({ ...k, at: srcToOutFrame(segments, k.atSrc, fps) ?? 0 }))
  const active = keys.filter((k) => k.at <= frame)
  const target = active.at(-1) ?? keys[0]
  const previous = active.at(-2) ?? target
  const move = interpolate(frame, [target.at, target.at + CAMERA_MOVE_FRAMES], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: (t) => t * t * (3 - 2 * t),
  })
  const view = lerpBox(previous.box, target.box, move)
  const zoom = FRAME.width / view.width

  return (
    <AbsoluteFill style={{ background: theme.bg, fontFamily: theme.font, color: theme.text }}>
      <div
        style={{
          position: 'absolute',
          left: FRAME.x,
          top: 44,
          fontSize: 34,
          fontWeight: 800,
          display: 'flex',
          gap: 18,
          alignItems: 'center',
        }}
      >
        <span style={{ width: 12, height: 12, borderRadius: 6, background: theme.accent }} />
        {chapter(timeline, srcNow)}
        {current.speed > 1 && (
          <Chip color={theme.dim} style={{ fontSize: 18, padding: '3px 10px' }}>
            ×{current.speed} speed
          </Chip>
        )}
      </div>

      <div
        style={{
          position: 'absolute',
          left: FRAME.x,
          top: FRAME.y,
          width: FRAME.width,
          height: FRAME_H + TITLE_BAR,
          borderRadius: 14,
          overflow: 'hidden',
          border: `1.5px solid ${theme.border}`,
          boxShadow: '0 30px 80px rgba(0,0,0,.45)',
        }}
      >
        <div
          style={{
            height: TITLE_BAR,
            background: theme.panel,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '0 14px',
            fontSize: 16,
            color: theme.dim,
          }}
        >
          {['#f87171', '#f5b942', '#34d399'].map((c) => (
            <span key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />
          ))}
          <span style={{ marginLeft: 12 }}>IncidentFlow — Operations console</span>
        </div>
        <div style={{ position: 'relative', width: FRAME.width, height: FRAME_H, overflow: 'hidden' }}>
          <div
            style={{
              position: 'absolute',
              width: SRC_W,
              height: 1080,
              transformOrigin: 'top left',
              transform: `translate(${-view.x * zoom}px, ${-view.y * zoom}px) scale(${zoom})`,
            }}
          >
            {placed.map((s) => (
              <Sequence key={s.from} from={s.from} durationInFrames={s.duration} layout="none">
                <OffthreadVideo
                  src={staticFile(timeline.recording)}
                  startFrom={Math.round(s.srcFrom * fps)}
                  endAt={Math.round(s.srcTo * fps)}
                  playbackRate={s.speed}
                  muted
                  style={{ width: SRC_W, height: 1080, position: 'absolute', inset: 0 }}
                />
              </Sequence>
            ))}
            {masks.map((m, i) => (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: m.box.x,
                  top: m.box.y,
                  width: m.box.width,
                  height: m.box.height,
                  backdropFilter: 'blur(12px)',
                  background: 'rgba(148,163,184,.35)',
                  borderRadius: 6,
                }}
              />
            ))}
          </div>
        </div>
      </div>

      <div style={{ position: 'absolute', left: COLUMN.x, top: FRAME.y, width: COLUMN.width }}>
        {callouts.map(({ callout, enter }) => (
          <CalloutCard key={`${callout.title}-${callout.atSrc}`} callout={callout} enterFrame={enter} />
        ))}
      </div>
    </AbsoluteFill>
  )
}
