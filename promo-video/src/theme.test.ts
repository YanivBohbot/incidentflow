import { describe, expect, it } from 'vitest'
import { theme } from './theme'

describe('theme', () => {
  it('uses the app sidebar navy', () => {
    expect(theme.bg).toBe('#0b1730')
  })
  it('defines every color as a 6-digit hex', () => {
    const colors = Object.entries(theme).filter(([key]) => key !== 'font')
    for (const [, value] of colors) expect(value).toMatch(/^#[0-9a-f]{6}$/)
  })
})
