import { AbsoluteFill } from 'remotion'
import { Chip, Reveal, sceneStyle, useSceneFade } from '../components/ui'
import { STACK, architecture } from '../content/architecture'
import { theme } from '../theme'

const box = {
  border: `1.5px solid ${theme.border}`,
  background: theme.panel,
  borderRadius: 14,
  padding: '16px 18px',
} as const

/** The whole architecture, built up once more as a recap, plus the stack. */
export function Recap({ durationInFrames }: { durationInFrames: number }) {
  const fade = useSceneFade(durationInFrames)
  return (
    <AbsoluteFill style={{ ...sceneStyle, opacity: fade }}>
      <div style={{ width: 1680, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 26 }}>
        <Reveal>
          <div style={{ ...box, borderColor: theme.accent, textAlign: 'center', padding: '20px 40px' }}>
            <div style={{ fontSize: 40, fontWeight: 800 }}>{architecture.supervisor}</div>
            <div style={{ fontSize: 24, color: theme.dim, marginTop: 6 }}>
              {architecture.supervisorFramework}
            </div>
          </div>
        </Reveal>
        <Reveal delay={12}>
          <div style={{ fontSize: 26, color: theme.accent, fontWeight: 700 }}>
            ↓ agents as tools ↓
          </div>
        </Reveal>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 18, width: '100%' }}>
          {architecture.agents.map((agent, i) => (
            <Reveal key={agent.tool} delay={20 + i * 7}>
              <div style={{ ...box, height: 150 }}>
                <div style={{ fontSize: 28, fontWeight: 800 }}>{agent.short}</div>
                <div style={{ fontSize: 20, color: theme.dim, marginTop: 4, fontFamily: 'Consolas, monospace' }}>
                  {agent.tool}
                </div>
                <div style={{ fontSize: 21, color: theme.accent, marginTop: 14 }}>{agent.source}</div>
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal delay={60} style={{ width: '100%' }}>
          <div
            style={{
              ...box,
              borderStyle: 'dashed',
              fontSize: 21,
              color: theme.dim,
              textAlign: 'center',
              lineHeight: 1.6,
            }}
          >
            <span style={{ color: theme.text, fontWeight: 700 }}>Middleware · </span>
            HumanInTheLoop · ReadOnlyPolicy · RepositoryAllowlist · ExternalEvidenceBoundary ·
            ToolCallLimit · ModelCallLimit · ToolRetry · LLMToolSelector · TruncateToolOutput
          </div>
        </Reveal>
        <Reveal delay={85}>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', justifyContent: 'center' }}>
            {STACK.map((item) => (
              <Chip key={item} color={theme.text} style={{ fontSize: 24 }}>
                {item}
              </Chip>
            ))}
          </div>
        </Reveal>
        <Reveal delay={105}>
          <div style={{ fontSize: 22, color: theme.dim }}>
            Scenarios are realistic simulations running on real integrations.
          </div>
        </Reveal>
      </div>
    </AbsoluteFill>
  )
}
