import { AbsoluteFill, Composition } from 'remotion'
import { FPS, HEIGHT, WIDTH, theme } from './theme'

const Placeholder = () => <AbsoluteFill style={{ background: theme.bg }} />

export const Root = () => (
  <Composition
    id="IncidentFlowPromo"
    component={Placeholder}
    durationInFrames={90 * FPS}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
)
