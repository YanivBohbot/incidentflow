import { type CameraKey, FOCUS } from '../timeline/camera'
import type { Segment, Timeline } from '../timeline/types'
import { agentByTool } from './architecture'

/** The tour is short holds on each report: one uniform speed-up keeps every report readable. */
export const TOUR_SPEED = 2

export type TourScenario = { atSrc: number; service: string; title: string; agents: string[] }

/** The past investigations shown in the tour, with the specialists each one used. */
export function tourScenarios(timeline: Timeline): TourScenario[] {
  return timeline.events
    .filter((e) => e.kind === 'click' && e.label.startsWith('[Demo]'))
    .map((e) => {
      const match = /^\[Demo\]\s*(.*?)\s*\(([^)]+)\)\s*$/.exec(e.label)
      const agents = [...new Set(e.agents ?? [])].map((tool) => agentByTool(tool)?.short ?? tool)
      return {
        atSrc: e.t,
        service: match?.[2] ?? e.label,
        title: match?.[1] ?? e.label,
        agents,
      }
    })
}

/** Segments and camera for the tour recording. */
export function tourEdit(timeline: Timeline): { segments: Segment[]; keys: CameraKey[] } {
  const keys: CameraKey[] = [{ atSrc: 0, box: FOCUS.full }]
  const investigations = timeline.events.find((e) => e.kind === 'page' && e.label === 'Investigations')
  if (investigations) keys.push({ atSrc: investigations.t + 0.3, box: FOCUS.report })
  return { segments: [{ srcFrom: 0, srcTo: timeline.durationS, speed: TOUR_SPEED }], keys }
}
