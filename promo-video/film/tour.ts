/**
 * Film a tour of past demo investigations — no new investigation, no LLM cost.
 *
 *   npm run tour
 */
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, type Page } from 'playwright'
import type { Timeline, TimelineEvent } from '../src/timeline/types'
import { API_URL, WEB_URL } from './preflight'
import { boxOf, sensitiveBoxes } from './sensitive'

/** Shown in this order; refund-service is the live take, so it is not repeated here. */
export const TOUR = [
  '[Demo] Customers report missing orders (order-service)',
  '[Demo] Checkout down during flash sale (checkout-api)',
  '[Demo] Login failures after key rotation (auth-service)',
  '[Demo] inventory-service pods restarting (OOMKilled)',
  '[Demo] Slow search results (search-api)',
  '[Demo] payment-service HTTP 500 alarm (CloudWatch)',
]
const SIZE = { width: 1920, height: 1080 }
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

type Investigation = {
  id: string
  incident_id: string
  lifecycle: string
  report: { agents_consulted?: string[] } | null
}

async function main() {
  const incidents = (await (await fetch(`${API_URL}/api/incidents`)).json()) as { id: string; title: string }[]
  const investigations = (await (await fetch(`${API_URL}/api/investigations`)).json()) as Investigation[]
  const agentsFor = (title: string) => {
    const ids = new Set(incidents.filter((i) => i.title === title).map((i) => i.id))
    const done = investigations.find((i) => ids.has(i.incident_id) && i.lifecycle === 'COMPLETED')
    return [...new Set(done?.report?.agents_consulted ?? [])]
  }

  mkdirSync('footage', { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: 'footage', size: SIZE } })
  const page = await context.newPage()
  const start = Date.now()
  const now = () => (Date.now() - start) / 1000
  const events: TimelineEvent[] = []
  const masks: Timeline['masks'] = []
  const mark = (kind: TimelineEvent['kind'], label: string, extra: Partial<TimelineEvent> = {}) => {
    events.push({ t: now(), kind, label, ...extra })
    console.log(`${now().toFixed(1).padStart(6)}s  ${kind.padEnd(6)} ${label}`)
  }
  const protect = async (page: Page, seconds: number) => {
    const t = now()
    for (const box of await sensitiveBoxes(page)) masks.push({ from: t - 0.3, to: t + seconds, box })
  }
  const nav = async (label: string) => {
    await page.locator('nav.primary-navigation button', { hasText: label }).first().click()
    mark('page', label)
  }

  try {
    await page.goto(WEB_URL, { waitUntil: 'networkidle' })
    await nav('Incidents')
    await sleep(1500)
    for (const severity of ['Critical', 'High', 'All']) {
      await page.locator('.severity-filter button', { hasText: severity }).first().click()
      mark('click', `Filter ${severity}`)
      await sleep(1300)
    }
    await nav('Investigations')
    await sleep(1500)
    for (const title of TOUR) {
      const item = page
        .locator('.investigation-list button')
        .filter({ hasText: title })
        .filter({ hasText: 'Completed' })
        .first()
      await item.scrollIntoViewIfNeeded()
      await item.click()
      await sleep(900)
      await page.locator('.investigation-report').first().scrollIntoViewIfNeeded().catch(() => {})
      await sleep(300)
      mark('click', title, { agents: agentsFor(title), box: await boxOf(page, '.investigation-report') })
      await protect(page, 3.6)
      await sleep(3400)
    }
  } finally {
    const durationS = now()
    const video = page.video()
    await context.close()
    await browser.close()
    if (video) renameSync(await video.path(), join('footage', 'tour.webm'))
    const timeline: Timeline = { recording: 'tour.webm', durationS, investigationId: '', events, masks }
    writeFileSync(join('footage', 'tour.timeline.json'), JSON.stringify(timeline, null, 2))
    console.log(`Wrote footage/tour.webm (${durationS.toFixed(1)} s)`)
  }
}

void main()
