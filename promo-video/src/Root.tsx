import { Composition, type CalculateMetadataFunction, Series, staticFile } from 'remotion'
import { Demo, demoDurationFrames } from './scenes/Demo'
import { EndCard } from './scenes/EndCard'
import { Hook } from './scenes/Hook'
import { Problem } from './scenes/Problem'
import { Recap } from './scenes/Recap'
import { FPS, HEIGHT, WIDTH } from './theme'
import type { Timeline } from './timeline/types'

export const SCENE_FRAMES = { hook: 6 * FPS, problem: 9 * FPS, recap: 8 * FPS, end: 5 * FPS }

type Props = { timeline: Timeline | null; demoFrames: number }

const Promo = ({ timeline, demoFrames }: Props) => (
  <Series>
    <Series.Sequence durationInFrames={SCENE_FRAMES.hook}>
      <Hook durationInFrames={SCENE_FRAMES.hook} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.problem}>
      <Problem durationInFrames={SCENE_FRAMES.problem} />
    </Series.Sequence>
    {timeline && (
      <Series.Sequence durationInFrames={demoFrames}>
        <Demo timeline={timeline} />
      </Series.Sequence>
    )}
    <Series.Sequence durationInFrames={SCENE_FRAMES.recap}>
      <Recap durationInFrames={SCENE_FRAMES.recap} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.end}>
      <EndCard />
    </Series.Sequence>
  </Series>
)

const scenesTotal = Object.values(SCENE_FRAMES).reduce((a, b) => a + b, 0)

/** Load the filmed take (public/take.timeline.json) and size the video around it. */
const loadTake: CalculateMetadataFunction<Props> = async () => {
  const response = await fetch(staticFile('take.timeline.json'))
  if (!response.ok) return { durationInFrames: scenesTotal, props: { timeline: null, demoFrames: 0 } }
  const timeline = (await response.json()) as Timeline
  timeline.recording = 'take.webm'
  const demoFrames = demoDurationFrames(timeline, FPS)
  return { durationInFrames: scenesTotal + demoFrames, props: { timeline, demoFrames } }
}

const common = { fps: FPS, width: WIDTH, height: HEIGHT }

export const Root = () => (
  <Composition
    id="IncidentFlowPromo"
    component={Promo}
    durationInFrames={scenesTotal}
    defaultProps={{ timeline: null, demoFrames: 0 }}
    calculateMetadata={loadTake}
    {...common}
  />
)
