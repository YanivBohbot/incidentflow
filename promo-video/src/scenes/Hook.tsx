import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion'
import { Reveal, sceneStyle, useSceneFade } from '../components/ui'
import { theme } from '../theme'

/** "3 AM. refund-service is throwing 5xx errors. Here's how IncidentFlow investigates." */
export function Hook({ durationInFrames }: { durationInFrames: number }) {
  const frame = useCurrentFrame()
  const fade = useSceneFade(durationInFrames)
  const pulse = 0.55 + 0.45 * Math.abs(Math.sin(frame / 9))
  return (
    <AbsoluteFill style={{ ...sceneStyle, opacity: fade }}>
      <div style={{ width: 1300 }}>
        <Reveal>
          <div style={{ fontSize: 120, fontWeight: 800, letterSpacing: -4 }}>3 AM.</div>
        </Reveal>
        <Reveal delay={18}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginTop: 28 }}>
            <span
              style={{
                width: 30,
                height: 30,
                borderRadius: 15,
                background: theme.danger,
                opacity: pulse,
                boxShadow: `0 0 ${30 * pulse}px ${theme.danger}`,
              }}
            />
            <span style={{ fontSize: 60, fontWeight: 700 }}>
              <span style={{ color: theme.danger }}>refund-service</span> is throwing 5xx errors.
            </span>
          </div>
        </Reveal>
        <Reveal delay={60}>
          <div
            style={{
              fontSize: 46,
              color: theme.dim,
              marginTop: 56,
              opacity: interpolate(frame, [60, 80], [0, 1], { extrapolateRight: 'clamp' }),
            }}
          >
            Here&apos;s how <span style={{ color: theme.accent, fontWeight: 700 }}>IncidentFlow</span>{' '}
            investigates.
          </div>
        </Reveal>
      </div>
    </AbsoluteFill>
  )
}
