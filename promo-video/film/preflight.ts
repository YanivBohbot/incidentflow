import { execFileSync } from 'node:child_process'

export const API_URL = process.env.FILM_API_URL ?? 'http://127.0.0.1:8000'
export const WEB_URL = process.env.FILM_WEB_URL ?? 'http://127.0.0.1:5174'
const MONGO_MCP_URL = process.env.FILM_MONGO_MCP_URL ?? 'http://127.0.0.1:3000/mcp'

async function reachable(url: string): Promise<boolean> {
  try {
    await fetch(url, { signal: AbortSignal.timeout(4000) })
    return true // any HTTP answer means the server is up
  } catch {
    return false
  }
}

/** Fail fast, with the fix, before a take costs LLM calls. */
export async function preflight(): Promise<void> {
  const problems: string[] = []

  const ready = await fetch(`${API_URL}/health/ready`).then((r) => r.ok).catch(() => false)
  if (!ready) problems.push(`API not ready at ${API_URL}/health/ready — start the Docker stack.`)

  if (!(await reachable(WEB_URL))) problems.push(`Web app not reachable at ${WEB_URL}.`)

  if (!(await reachable(MONGO_MCP_URL))) {
    problems.push(`MongoDB MCP not answering at ${MONGO_MCP_URL} — start mongodb-mcp-server (see README).`)
  }

  try {
    const mounts = execFileSync('docker', [
      'inspect', '-f', '{{range .Mounts}}{{.Destination}} {{end}}', 'incidentflow-api-1',
    ]).toString()
    if (!mounts.includes('/home/incidentflow/.aws')) {
      problems.push(
        'API container has no AWS credentials — restart it with ' +
          '`docker compose -f docker-compose.yml -f docker-compose.cloudwatch.yml up -d api`.',
      )
    }
  } catch {
    problems.push('Cannot inspect container incidentflow-api-1 — is Docker running?')
  }

  if (problems.length > 0) {
    throw new Error(`Preflight failed:\n- ${problems.join('\n- ')}`)
  }
}
