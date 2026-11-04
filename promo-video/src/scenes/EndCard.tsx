import { AbsoluteFill } from 'remotion'
import { Reveal, sceneStyle } from '../components/ui'
import { theme } from '../theme'

/** Name and GitHub profile. The repo URL is added once the repository is announced. */
export function EndCard() {
  return (
    <AbsoluteFill style={sceneStyle}>
      <div style={{ textAlign: 'center' }}>
        <Reveal>
          <div style={{ display: 'flex', alignItems: 'center', gap: 28, justifyContent: 'center' }}>
            <span
              style={{
                width: 96,
                height: 96,
                borderRadius: 22,
                background: 'linear-gradient(135deg,#14b8a6,#0f766e)',
                display: 'grid',
                placeItems: 'center',
                fontSize: 44,
                fontWeight: 800,
              }}
            >
              IF
            </span>
            <span style={{ fontSize: 96, fontWeight: 800, letterSpacing: -3 }}>IncidentFlow</span>
          </div>
        </Reveal>
        <Reveal delay={14}>
          <div style={{ fontSize: 34, color: theme.dim, marginTop: 20 }}>
            Multi-agent incident investigation with a human in the loop
          </div>
        </Reveal>
        <Reveal delay={32}>
          <div style={{ fontSize: 48, fontWeight: 700, marginTop: 70 }}>Yaniv Bohbot</div>
          <div style={{ fontSize: 36, color: theme.accent, marginTop: 10, fontFamily: 'Consolas, monospace' }}>
            github.com/YanivBohbot
          </div>
        </Reveal>
      </div>
    </AbsoluteFill>
  )
}
