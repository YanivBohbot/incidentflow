import { describe, expect, it } from 'vitest'
import type { Timeline, TimelineEvent } from '../timeline/types'
import { FOCUS } from '../timeline/camera'
import { TOUR_SPEED, tourEdit, tourScenarios } from './tour'

const ev = (t: number, kind: TimelineEvent['kind'], label: string, agents?: string[]): TimelineEvent =>
  ({ t, kind, label, ...(agents ? { agents } : {}) })
const timeline: Timeline = {
  recording: 'tour.webm',
  durationS: 30,
  investigationId: '',
  masks: [],
  events: [
    ev(1.5, 'page', 'Incidents'),
    ev(3, 'click', 'Filter Critical'),
    ev(7, 'page', 'Investigations'),
    ev(10, 'click', '[Demo] Customers report missing orders (order-service)', [
      'ask_data_intelligence',
      'ask_cloudwatch',
    ]),
    ev(15, 'click', '[Demo] Login failures after key rotation (auth-service)', [
      'ask_data_intelligence',
      'ask_github',
      'ask_data_intelligence',
    ]),
  ],
}

describe('tourScenarios', () => {
  it('lists each visited scenario with its service and the agents the supervisor chose', () => {
    expect(tourScenarios(timeline)).toEqual([
      { atSrc: 10, service: 'order-service', title: 'Customers report missing orders', agents: ['Data Intelligence', 'CloudWatch'] },
      { atSrc: 15, service: 'auth-service', title: 'Login failures after key rotation', agents: ['Data Intelligence', 'GitHub'] },
    ])
  })
})

describe('tourEdit', () => {
  it('plays the whole tour at one speed and moves the camera onto the report on Investigations', () => {
    const { segments, keys } = tourEdit(timeline)
    expect(segments).toEqual([{ srcFrom: 0, srcTo: 30, speed: TOUR_SPEED }])
    expect(keys).toEqual([
      { atSrc: 0, box: FOCUS.full },
      { atSrc: 7.3, box: FOCUS.report },
    ])
  })
})
