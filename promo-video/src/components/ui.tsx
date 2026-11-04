import type { CSSProperties, ReactNode } from 'react'
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { theme } from '../theme'

/** 0→1 entrance progress starting at `delay` frames. */
export function useEnter(delay = 0, damping = 18): number {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return spring({ frame: frame - delay, fps, config: { damping } })
}

/** Fade + slide up, starting at `delay` frames. */
export function Reveal({
  delay = 0,
  children,
  style,
}: {
  delay?: number
  children: ReactNode
  style?: CSSProperties
}) {
  const p = useEnter(delay)
  return (
    <div style={{ opacity: p, transform: `translateY(${interpolate(p, [0, 1], [24, 0])}px)`, ...style }}>
      {children}
    </div>
  )
}

/** Fade the whole scene out over its last `frames` frames. */
export function useSceneFade(durationInFrames: number, frames = 12): number {
  const frame = useCurrentFrame()
  return interpolate(frame, [0, 8, durationInFrames - frames, durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })
}

export function Chip({
  children,
  color = theme.accent,
  style,
}: {
  children: ReactNode
  color?: string
  style?: CSSProperties
}) {
  return (
    <span
      style={{
        display: 'inline-block',
        border: `1.5px solid ${color}55`,
        background: `${color}14`,
        color,
        borderRadius: 10,
        padding: '8px 16px',
        fontSize: 26,
        fontWeight: 600,
        fontFamily: theme.font,
        ...style,
      }}
    >
      {children}
    </span>
  )
}

export const sceneStyle: CSSProperties = {
  background: `radial-gradient(ellipse at 30% 20%, #16284d 0%, ${theme.bg} 60%)`,
  color: theme.text,
  fontFamily: theme.font,
  justifyContent: 'center',
  alignItems: 'center',
}
