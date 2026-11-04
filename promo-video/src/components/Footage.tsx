import { OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'
import { type CameraKey, keysForSegments, lerpBox } from '../timeline/camera'
import { activeMasks } from '../timeline/masks'
import type { Segment, Timeline } from '../timeline/types'

const SRC_W = 1920
const SRC_H = 1080
const CAMERA_MOVE_FRAMES = 24

export type Placed = Segment & { from: number; duration: number }

/** Output frames of each edit segment, laid end to end. */
export function placeSegments(segments: Segment[], fps: number): Placed[] {
  let at = 0
  return segments.map((s) => {
    const duration = Math.max(1, Math.round(((s.srcTo - s.srcFrom) / s.speed) * fps))
    const item = { ...s, from: at, duration }
    at += duration
    return item
  })
}

export const placedDuration = (placed: Placed[]) => placed.reduce((sum, s) => sum + s.duration, 0)

/** Source time shown at output `frame`, and the segment it belongs to. */
export function sourceAt(placed: Placed[], frame: number, fps: number) {
  const current = placed.find((s) => frame >= s.from && frame < s.from + s.duration) ?? placed.at(-1)!
  return { current, srcNow: current.srcFrom + ((frame - current.from) / fps) * current.speed }
}

type Props = {
  timeline: Timeline
  segments: Segment[]
  keys: CameraKey[]
  width: number
  height: number
}

/** The real recording, cut by `segments`, framed by a camera that follows `keys`, with masks. */
export function Footage({ timeline, segments, keys, width, height }: Props) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const placed = placeSegments(segments, fps)
  const { srcNow } = sourceAt(placed, frame, fps)

  const timed = keysForSegments(keys, segments, fps)
  const active = timed.filter((k) => k.at <= frame)
  const target = active.at(-1) ?? timed[0]
  const previous = active.at(-2) ?? target
  const move = interpolate(frame, [target.at, target.at + CAMERA_MOVE_FRAMES], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: (t) => t * t * (3 - 2 * t),
  })
  const view = lerpBox(previous.box, target.box, move)
  const zoom = width / view.width
  const masks = activeMasks(timeline, srcNow)

  return (
    <div style={{ position: 'relative', width, height, overflow: 'hidden', background: '#f5f7fb' }}>
      <div
        style={{
          position: 'absolute',
          width: SRC_W,
          height: SRC_H,
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
              style={{ width: SRC_W, height: SRC_H, position: 'absolute', inset: 0 }}
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
              background: 'rgb(203,213,225)',
              borderRadius: 6,
            }}
          />
        ))}
      </div>
    </div>
  )
}
