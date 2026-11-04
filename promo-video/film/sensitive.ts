import type { Page } from 'playwright'
import type { Box } from '../src/timeline/types'

/**
 * Text that must never be readable on screen: Jira site names, 12-digit AWS account IDs, and
 * UUIDs (the Jira cloudId identifies the site).
 */
const SENSITIVE = String.raw`atlassian\.net|\b\d{12}\b|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`

// Plain string on purpose: tsx/esbuild adds a `__name` helper to compiled functions, which does
// not exist in the page, so a function passed to page.evaluate would throw there.
const SENSITIVE_BOXES_JS = `(args) => {
  const re = new RegExp(args.pattern)
  const boxes = []
  const push = (el) => {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight) {
      boxes.push({ x: r.x - 6, y: r.y - 4, width: r.width + 12, height: r.height + 8 })
    }
  }
  if (args.extra) document.querySelectorAll(args.extra).forEach(push)
  document.querySelectorAll('body *').forEach((el) => {
    if (el.children.length === 0 && re.test(el.textContent || '')) push(el)
  })
  return boxes
}`

/** Boxes of visible elements whose text looks sensitive, plus any `extraSelector` matches. */
export async function sensitiveBoxes(page: Page, extraSelector?: string): Promise<Box[]> {
  const args = JSON.stringify({ pattern: SENSITIVE, extra: extraSelector ?? null })
  return page.evaluate(`(${SENSITIVE_BOXES_JS})(${args})`) as Promise<Box[]>
}

/** Viewport box of the first element matching `selector`, or undefined. */
export async function boxOf(page: Page, selector: string): Promise<Box | undefined> {
  const box = await page.locator(selector).first().boundingBox().catch(() => null)
  return box ?? undefined
}
