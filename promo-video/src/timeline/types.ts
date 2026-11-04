/** Viewport pixels of the 1920×1080 recording. */
export type Box = { x: number; y: number; width: number; height: number }

export type TimelineEventKind =
  | 'page'
  | 'click'
  | 'trace_step'
  | 'hitl_pause'
  | 'typing_start'
  | 'typing_end'
  | 'approved'
  | 'completed'

/** Something that happened during a take, `t` seconds after the recording started. */
export type TimelineEvent = {
  t: number
  kind: TimelineEventKind
  label: string
  agent?: string
  tool?: string
  /** For trace_step: the API trace kind (delegation, subagent_call, finding, report…). */
  stepKind?: string
  box?: Box
}

export type Timeline = {
  recording: string
  durationS: number
  investigationId: string
  events: TimelineEvent[]
  masks: { from: number; to: number; box: Box }[]
}

/** A span of the source recording and the speed it plays at in the video. */
export type Segment = { srcFrom: number; srcTo: number; speed: number }
