import type { ReactNode } from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { theme } from '../theme'
import { Chip } from './ui'

/** App window on the left, explanation column on the right. */
export const FRAME = { x: 60, y: 120, width: 1300 }
export const FRAME_H = Math.round((1080 * FRAME.width) / 1920)
const TITLE_BAR = 36
export const COLUMN = { x: FRAME.x + FRAME.width + 40, width: 1920 - (FRAME.x + FRAME.width + 40) - 50 }

export function Stage({
  heading,
  badge,
  window,
  column,
}: {
  heading: string
  badge?: string
  window: ReactNode
  column: ReactNode
}) {
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
        {heading}
        {badge && (
          <Chip color={theme.dim} style={{ fontSize: 18, padding: '3px 10px' }}>
            {badge}
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
        {window}
      </div>
      <div style={{ position: 'absolute', left: COLUMN.x, top: FRAME.y, width: COLUMN.width }}>
        {column}
      </div>
    </AbsoluteFill>
  )
}

/** Explanation card that slides in at `enterFrame`. */
export function Card({
  enterFrame,
  title,
  body,
  chips = [],
  tone,
}: {
  enterFrame: number
  title: string
  body?: string
  chips?: string[]
  tone?: 'accent' | 'warn' | 'ok'
}) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const p = spring({ frame: frame - enterFrame, fps, config: { damping: 18 } })
  const color = tone === 'warn' ? theme.warn : tone === 'ok' ? theme.ok : theme.accent
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
      <div style={{ fontSize: 28, fontWeight: 800, color: theme.text }}>{title}</div>
      {body && <div style={{ fontSize: 21, color: theme.dim, marginTop: 8, lineHeight: 1.4 }}>{body}</div>}
      {chips.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
          {chips.map((chip) => (
            <Chip key={chip} color={color} style={{ fontSize: 16, padding: '4px 10px' }}>
              {chip}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}
