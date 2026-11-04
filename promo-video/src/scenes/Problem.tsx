import { AbsoluteFill } from 'remotion'
import { Chip, Reveal, sceneStyle, useSceneFade } from '../components/ui'
import { theme } from '../theme'

const SOURCES = ['CloudWatch logs', 'Alarms', 'GitHub commits', 'MongoDB events', 'Runbooks', 'Jira']

/** The on-call problem: the context lives in six different tools. */
export function Problem({ durationInFrames }: { durationInFrames: number }) {
  const fade = useSceneFade(durationInFrames)
  return (
    <AbsoluteFill style={{ ...sceneStyle, opacity: fade }}>
      <div style={{ width: 1400, textAlign: 'center' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 22, justifyContent: 'center' }}>
          {SOURCES.map((source, i) => (
            <Reveal key={source} delay={i * 9}>
              <Chip color={i % 2 ? theme.warn : theme.dim} style={{ fontSize: 34, padding: '14px 26px' }}>
                {source}
              </Chip>
            </Reveal>
          ))}
        </div>
        <Reveal delay={70}>
          <div style={{ fontSize: 64, fontWeight: 800, marginTop: 80, letterSpacing: -1.5 }}>
            The context is scattered across tools.
          </div>
        </Reveal>
        <Reveal delay={110}>
          <div style={{ fontSize: 40, color: theme.dim, marginTop: 26 }}>
            Every minute spent switching tabs is a minute of outage.
          </div>
        </Reveal>
      </div>
    </AbsoluteFill>
  )
}
