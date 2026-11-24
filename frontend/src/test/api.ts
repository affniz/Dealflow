import { vi } from "vitest"

type Reply =
  { status?: number; json?: unknown } | ((request: Request) => Response | Promise<Response>)

export type Call = { method: string; path: string; body: unknown; headers: Headers }

/**
 * Stand in for the API: answers the generated client's requests from `routes`, keyed by
 * "METHOD /api/v1/path" (exact path, no query string), and records every call. A request
 * nothing answers fails the test with the request in the message.
 */
export function mockApi(routes: Record<string, Reply>) {
  const calls: Call[] = []
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    const url = new URL(request.url)
    const key = `${request.method} ${url.pathname}`
    const text = await request.clone().text()
    let body: unknown = text
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      // a form body (sign-in) stays as text
    }
    calls.push({ method: request.method, path: url.pathname, body, headers: request.headers })
    const reply = routes[key]
    if (reply === undefined) throw new Error(`Unexpected API call: ${key}`)
    let response: Response
    if (typeof reply === "function") response = await reply(request)
    else {
      const status = reply.status ?? 200
      response =
        status === 204
          ? new Response(null, { status })
          : Response.json(reply.json ?? null, { status })
    }
    // a real response knows its URL, and the app reads it (see onSessionExpired in lib/auth)
    Object.defineProperty(response, "url", { value: request.url })
    return response
  })
  vi.stubGlobal("fetch", fetch)
  return { calls, fetch }
}
