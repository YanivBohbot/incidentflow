/**
 * Film one real IncidentFlow investigation, end to end, and write its timeline.
 *
 *   npm run film -- --take 1            # live take (real LLM, AWS, GitHub, MongoDB, Jira calls)
 *   npm run film -- --take 0 --rehearse # same path, stops before launching the investigation
 */
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, type Page } from 'playwright'
import type { Timeline, TimelineEvent } from '../src/timeline/types'
import { API_URL, WEB_URL, preflight } from './preflight'
import { sensitiveBoxes } from './sensitive'
import { diffTraceSteps, type TraceStep } from './traceWatcher'

const INCIDENT_TITLE = '[Demo] Refund requests failing (refund-service)'
const APPROVAL_NOTE =
  'Verified against CloudWatch, GitHub PR #7 and the runbook. Approved — create the SAM1 task.'
const TIMEOUT_S = 300
const SIZE = { width: 1920, height: 1080 }
const args = process.argv.slice(2)
const take = Number(args[args.indexOf('--take') + 1] ?? 0)
const rehearse = args.includes('--rehearse')

type Investigation = { id: string; incident_id: string; lifecycle: string; created_at: string }

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const getJson = async <T>(path: string): Promise<T> => {
  const response = await fetch(`${API_URL}${path}`)
  if (!response.ok) throw new Error(`${path} → HTTP ${response.status}`)
  return (await response.json()) as T
}

class Recorder {
  readonly events: TimelineEvent[] = []
  readonly masks: Timeline['masks'] = []
  private readonly start = Date.now()
  now = () => (Date.now() - this.start) / 1000
  mark(kind: TimelineEvent['kind'], label: string, extra: Partial<TimelineEvent> = {}) {
    this.events.push({ t: this.now(), kind, label, ...extra })
    console.log(`${this.now().toFixed(1).padStart(6)}s  ${kind.padEnd(12)} ${label}`)
  }
}

async function nav(page: Page, rec: Recorder, label: string) {
  await page.locator('nav.primary-navigation button', { hasText: label }).first().click()
  rec.mark('page', label)
}

async function main() {
  await preflight()
  mkdirSync('footage', { recursive: true })

  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: SIZE,
    deviceScaleFactor: 1,
    recordVideo: { dir: 'footage', size: SIZE },
  })
  const page = await context.newPage()
  const rec = new Recorder()
  let investigationId = ''
  let exitCode = 0

  try {
    await page.goto(WEB_URL, { waitUntil: 'networkidle' })
    rec.mark('page', 'Overview')
    await sleep(3000)

    await nav(page, rec, 'Incidents')
    await sleep(1500)
    await page.locator('.incident-list button', { hasText: INCIDENT_TITLE }).click()
    rec.mark('click', 'Select incident')
    await sleep(2500)

    if (rehearse) {
      await page.getByRole('button', { name: 'Launch multi-agent investigation' }).hover()
      await sleep(1500)
      console.log('Rehearsal: stopping before launch.')
      return
    }

    const launchedAt = Date.now()
    await page.getByRole('button', { name: 'Launch multi-agent investigation' }).click()
    rec.mark('click', 'Launch investigation')

    // Find the investigation the click created.
    const incidents = await getJson<{ id: string; title: string }[]>('/api/incidents')
    const incidentId = incidents.find((i) => i.title === INCIDENT_TITLE)?.id
    while (!investigationId) {
      const items = await getJson<Investigation[]>('/api/investigations')
      const mine = items.find(
        (i) => i.incident_id === incidentId && Date.parse(i.created_at) >= launchedAt - 5000,
      )
      if (mine) investigationId = mine.id
      else await sleep(500)
      if (rec.now() > TIMEOUT_S) throw Object.assign(new Error('Investigation never appeared'), { code: 3 })
    }

    let steps: TraceStep[] = []
    let approved = false
    let sawPause = false
    const poll = async () => {
      const next = await getJson<TraceStep[]>(`/api/investigations/${investigationId}/trace`)
      for (const event of diffTraceSteps(steps, next, rec.now())) {
        rec.events.push(event)
        console.log(`${event.t.toFixed(1).padStart(6)}s  ${event.kind.padEnd(12)} ${event.label}`)
        if (event.kind === 'hitl_pause') sawPause = true
      }
      steps = next
      const t = rec.now()
      for (const box of await sensitiveBoxes(page)) rec.masks.push({ from: t - 0.2, to: t + 1.4, box })
      await page.locator('.trace-step').last().scrollIntoViewIfNeeded({ timeout: 500 }).catch(() => {})
    }

    for (;;) {
      await poll()
      const { lifecycle } = await getJson<Investigation>(`/api/investigations/${investigationId}`)
      if (lifecycle === 'FAILED') throw Object.assign(new Error('Investigation FAILED'), { code: 3 })
      if (lifecycle === 'COMPLETED' && !approved) {
        throw Object.assign(
          new Error("No HITL pause — delete this scenario's SAM1 tickets, then film again."),
          { code: 2 },
        )
      }
      if (lifecycle === 'COMPLETED') break
      if (lifecycle === 'AWAITING_HUMAN_REVIEW' && !approved) {
        if (!sawPause) rec.mark('hitl_pause', 'Paused before createJiraIssue')
        const panel = page.locator('.human-review-panel').first()
        await panel.waitFor({ timeout: 20000 })
        rec.mark('page', 'Approvals')
        // Mask only identifying values (the Jira cloudId), re-measured after every scroll.
        const maskFor = async (seconds: number) => {
          const t = rec.now()
          for (const box of await sensitiveBoxes(page)) rec.masks.push({ from: t - 0.3, to: t + seconds, box })
        }
        const showTop = async (selector: string) => {
          await page.evaluate(
            `document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: 'start' })`,
          )
          await sleep(400)
        }
        // 1. The request: createJiraIssue, project SAM1, issue type.
        await showTop('.human-review-panel')
        await maskFor(4)
        await sleep(3500)
        // 2. The drafted ticket: summary and description written by the agents.
        rec.mark('page', 'Review draft')
        await showTop('.human-review-panel .review-field')
        await maskFor(5)
        await sleep(4500)
        // 3. The operator note and the decision buttons.
        const note = panel.locator('.proposal-actions textarea')
        await showTop('.human-review-panel .proposal-actions')
        await maskFor(15)
        await note.click()
        rec.mark('typing_start', 'Operator types approval note')
        await note.pressSequentially(APPROVAL_NOTE, { delay: 45 })
        rec.mark('typing_end', 'Approval note typed')
        await sleep(1200)
        await panel.getByRole('button', { name: /^Approve/ }).click()
        rec.mark('approved', 'Approve and resume')
        approved = true
        await sleep(1500)
        await nav(page, rec, 'Investigations')
      }
      if (rec.now() > TIMEOUT_S) throw Object.assign(new Error('Investigation timed out'), { code: 3 })
      await sleep(1000)
    }
    await poll()
    rec.mark('completed', 'Investigation completed')
    await sleep(4000)
  } catch (error) {
    exitCode = (error as { code?: number }).code ?? 1
    console.error(`Take ${take} aborted: ${(error as Error).message}`)
  } finally {
    const durationS = rec.now()
    const video = page.video()
    await context.close()
    await browser.close()
    const target = join('footage', `take-${take}.webm`)
    if (video) renameSync(await video.path(), target)
    const timeline: Timeline = {
      recording: `take-${take}.webm`,
      durationS,
      investigationId,
      events: rec.events,
      masks: rec.masks,
    }
    writeFileSync(join('footage', `take-${take}.timeline.json`), JSON.stringify(timeline, null, 2))
    console.log(`Wrote ${target} (${durationS.toFixed(1)} s), exit ${exitCode}`)
    process.exitCode = exitCode
  }
}

void main()
