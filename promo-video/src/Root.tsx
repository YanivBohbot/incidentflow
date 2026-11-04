import { AbsoluteFill, Composition, Series } from 'remotion'
import { EndCard } from './scenes/EndCard'
import { Hook } from './scenes/Hook'
import { Problem } from './scenes/Problem'
import { Recap } from './scenes/Recap'
import { FPS, HEIGHT, WIDTH, theme } from './theme'

export const SCENE_FRAMES = { hook: 6 * FPS, problem: 9 * FPS, recap: 8 * FPS, end: 5 * FPS }

const Placeholder = () => <AbsoluteFill style={{ background: theme.bg }} />

const Promo = () => (
  <Series>
    <Series.Sequence durationInFrames={SCENE_FRAMES.hook}>
      <Hook durationInFrames={SCENE_FRAMES.hook} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.problem}>
      <Problem durationInFrames={SCENE_FRAMES.problem} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.recap}>
      <Recap durationInFrames={SCENE_FRAMES.recap} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.end}>
      <EndCard />
    </Series.Sequence>
  </Series>
)

const total = Object.values(SCENE_FRAMES).reduce((a, b) => a + b, 0)
const common = { fps: FPS, width: WIDTH, height: HEIGHT }

export const Root = () => (
  <>
    <Composition id="IncidentFlowPromo" component={Promo} durationInFrames={total} {...common} />
    <Composition id="Placeholder" component={Placeholder} durationInFrames={30} {...common} />
  </>
)
