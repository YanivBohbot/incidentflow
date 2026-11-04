import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { architecture } from './architecture'

const API_SRC = join(__dirname, '../../../apps/api/src')

function sourceText(dir: string): string {
  return readdirSync(dir)
    .map((name) => join(dir, name))
    .map((path) =>
      statSync(path).isDirectory()
        ? sourceText(path)
        : path.endsWith('.py')
          ? readFileSync(path, 'utf8')
          : '',
    )
    .join('\n')
}

describe('architecture facts shown on screen', () => {
  const source = sourceText(API_SRC)
  const names = [
    ...architecture.agents.flatMap((agent) => agent.middleware),
    ...architecture.supervisorMiddleware,
    ...architecture.sharedMiddleware,
  ].filter((name) => name.endsWith('Middleware'))

  it('only names middleware that exists in the API code', () => {
    expect(names.length).toBeGreaterThan(5)
    for (const name of names) expect(source, name).toContain(name)
  })

  it('only names delegation tools that exist in the API code', () => {
    for (const agent of architecture.agents) expect(source).toContain(`"${agent.tool}"`)
  })
})
