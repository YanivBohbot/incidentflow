import { Composition, type CalculateMetadataFunction, Series, staticFile } from 'remotion'
import { Demo, demoDurationFrames } from './scenes/Demo'
import { EndCard } from './scenes/EndCard'
import { Hook } from './scenes/Hook'
import { JIRA_FRAMES, JIRA_SHOT, JiraTicket } from './scenes/JiraTicket'
import { Loop, loopDurationFrames } from './scenes/Loop'
import { Problem } from './scenes/Problem'
import { Recap } from './scenes/Recap'
import { Tour, tourDurationFrames } from './scenes/Tour'
import { FPS, HEIGHT, WIDTH } from './theme'
import type { Timeline } from './timeline/types'

export const SCENE_FRAMES = { hook: 6 * FPS, problem: 9 * FPS, recap: 8 * FPS, end: 5 * FPS }
const scenesTotal = Object.values(SCENE_FRAMES).reduce((a, b) => a + b, 0)

type Takes = { take: Timeline | null; tour: Timeline | null }
type PromoProps = Takes & {
  jira: boolean
  demoFrames: number
  jiraFrames: number
  tourFrames: number
}

async function loadTimeline(name: string, recording: string): Promise<Timeline | null> {
  const response = await fetch(staticFile(name))
  if (!response.ok) return null
  const timeline = (await response.json()) as Timeline
  timeline.recording = recording
  return timeline
}

const loadTakes = async (): Promise<Takes> => ({
  take: await loadTimeline('take.timeline.json', 'take.webm'),
  tour: await loadTimeline('tour.timeline.json', 'tour.webm'),
})

const Promo = ({ take, tour, jira, demoFrames, jiraFrames, tourFrames }: PromoProps) => (
  <Series>
    <Series.Sequence durationInFrames={SCENE_FRAMES.hook}>
      <Hook durationInFrames={SCENE_FRAMES.hook} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={SCENE_FRAMES.problem}>
      <Problem durationInFrames={SCENE_FRAMES.problem} />
    </Series.Sequence>
    {take && (
      <Series.Sequence durationInFrames={demoFrames}>
        <Demo timeline={take} />
      </Series.Sequence>
    )}
    {jira && (
      <Series.Sequence durationInFrames={jiraFrames}>
        <JiraTicket />
      </Series.Sequence>
    )}
    {tour && (
      <Series.Sequence durationInFrames={tourFrames}>
        <Tour timeline={tour} />
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

const promoMetadata: CalculateMetadataFunction<PromoProps> = async () => {
  const { take, tour } = await loadTakes()
  const jira = (await fetch(staticFile(JIRA_SHOT.file))).ok
  const demoFrames = take ? demoDurationFrames(take, FPS) : 0
  const jiraFrames = jira ? JIRA_FRAMES : 0
  const tourFrames = tour ? tourDurationFrames(tour, FPS) : 0
  return {
    durationInFrames: scenesTotal + demoFrames + jiraFrames + tourFrames,
    props: { take, tour, jira, demoFrames, jiraFrames, tourFrames },
  }
}

type LoopProps = Takes
const LoopComposition = ({ take, tour }: LoopProps) =>
  take && tour ? <Loop take={take} tour={tour} fps={FPS} /> : null

const loopMetadata: CalculateMetadataFunction<LoopProps> = async () => {
  const { take, tour } = await loadTakes()
  if (!take || !tour) throw new Error('public/take.* and public/tour.* are required for the loop')
  const d = loopDurationFrames(tour, take, FPS)
  return { durationInFrames: d, props: { take, tour } }
}

const common = { fps: FPS, width: WIDTH, height: HEIGHT }

export const Root = () => (
  <>
    <Composition
      id="IncidentFlowPromo"
      component={Promo}
      durationInFrames={scenesTotal}
      defaultProps={{ take: null, tour: null, jira: false, demoFrames: 0, jiraFrames: 0, tourFrames: 0 }}
      calculateMetadata={promoMetadata}
      {...common}
    />
    <Composition
      id="IncidentFlowLoop"
      component={LoopComposition}
      durationInFrames={30}
      defaultProps={{ take: null, tour: null }}
      calculateMetadata={loopMetadata}
      {...common}
    />
  </>
)
