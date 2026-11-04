/**
 * Film the real Jira ticket the take created.
 *
 *   $env:FILM_JIRA_SITE = "https://<site>.atlassian.net"
 *   npm run jira -- --login          # opens a window: sign in to Jira once, then close it
 *   npm run jira -- --issue SAM1-23  # films the ticket page (headless, same browser profile)
 *
 * The site URL is read from the environment so it never lands in the repository, and the URL
 * bar is never recorded (viewport only).
 */
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright'
import type { Timeline, TimelineEvent } from '../src/timeline/types'
import { sensitiveBoxes } from './sensitive'

const SIZE = { width: 1920, height: 1080 }
const PROFILE = join('footage', 'jira-profile')
const site = process.env.FILM_JIRA_SITE
const args = process.argv.slice(2)
const issue = args.includes('--issue') ? args[args.indexOf('--issue') + 1] : undefined
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function login() {
  const context = await chromium.launchPersistentContext(PROFILE, { headless: false, viewport: null })
  const page = context.pages()[0] ?? (await context.newPage())
  await page.goto(`${site}/jira`)
  console.log('Sign in to Jira in the opened window, then close the window.')
  await new Promise<void>((resolve) => context.on('close', () => resolve()))
}

async function film(key: string) {
  const context = await chromium.launchPersistentContext(PROFILE, {
    headless: true,
    viewport: SIZE,
    recordVideo: { dir: 'footage', size: SIZE },
  })
  const page = context.pages()[0] ?? (await context.newPage())
  const start = Date.now()
  const now = () => (Date.now() - start) / 1000
  const events: TimelineEvent[] = []
  const masks: Timeline['masks'] = []
  const protect = async (seconds: number) => {
    const t = now()
    for (const box of await sensitiveBoxes(page)) masks.push({ from: t - 0.3, to: t + seconds, box })
  }
  try {
    await page.goto(`${site}/browse/${key}`, { waitUntil: 'domcontentloaded' })
    await page.getByText(key, { exact: true }).first().waitFor({ timeout: 30000 })
    if (page.url().includes('login') || page.url().includes('id.atlassian.com')) {
      throw new Error('Not signed in — run `npm run jira -- --login` first.')
    }
    await sleep(2500)
    events.push({ t: now(), kind: 'page', label: `Jira ${key}` })
    await protect(6)
    await sleep(5500)
    await page.mouse.move(700, 600)
    await page.mouse.wheel(0, 450)
    await sleep(800)
    events.push({ t: now(), kind: 'page', label: 'Jira description' })
    await protect(6)
    await sleep(5000)
  } finally {
    const durationS = now()
    const video = page.video()
    await context.close()
    if (video) renameSync(await video.path(), join('footage', 'jira.webm'))
    const timeline: Timeline = { recording: 'jira.webm', durationS, investigationId: key, events, masks }
    writeFileSync(join('footage', 'jira.timeline.json'), JSON.stringify(timeline, null, 2))
    console.log(`Wrote footage/jira.webm (${durationS.toFixed(1)} s), ${masks.length} masks`)
  }
}

async function main() {
  if (!site) throw new Error('Set FILM_JIRA_SITE to your Jira site URL (https://<site>.atlassian.net).')
  mkdirSync('footage', { recursive: true })
  if (args.includes('--login')) return login()
  if (!issue) throw new Error('Pass --issue <KEY>, e.g. --issue SAM1-23')
  return film(issue)
}

void main().catch((error: Error) => {
  console.error(error.message)
  process.exitCode = 1
})
