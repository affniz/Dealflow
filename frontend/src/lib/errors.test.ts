import { beforeEach, describe, expect, it, vi } from "vitest"

import { mockApi } from "@/test/api"

// reportError remembers what it sent, so each test loads a fresh copy
let errors: typeof import("@/lib/errors")
beforeEach(async () => {
  vi.resetModules()
  errors = await import("@/lib/errors")
})

describe("isStaleBuildError", () => {
  it("recognises each browser's wording for a missing page file", () => {
    for (const message of [
      "Failed to fetch dynamically imported module: /assets/DealPage-1a2b.js",
      "Importing a module script failed.",
      "error loading dynamically imported module",
      "Unable to preload CSS for /assets/x.css",
    ]) {
      expect(errors.isStaleBuildError(new TypeError(message))).toBe(true)
    }
    expect(errors.isStaleBuildError(new TypeError("x is undefined"))).toBe(false)
  })
})

describe("reloadForUpdate", () => {
  it("reloads once, then not again within 10 seconds", () => {
    const assign = vi.fn()
    vi.stubGlobal("location", { ...window.location, assign, reload: vi.fn() })
    expect(errors.reloadForUpdate("/dashboard")).toBe(true)
    expect(assign).toHaveBeenCalledWith("/dashboard")
    expect(errors.reloadForUpdate("/dashboard")).toBe(false)
    expect(assign).toHaveBeenCalledTimes(1)
  })
})

describe("reportError", () => {
  it("sends the error and the page's path, never its query or #", async () => {
    window.history.pushState({}, "", "/reset-password?x=1#dfp_secret")
    const api = mockApi({ "POST /api/v1/client-errors": { status: 204 } })
    const error = new TypeError("deal.stage is undefined")
    errors.reportError(error, "\n    at DealCard")
    await vi.waitFor(() => expect(api.calls).toHaveLength(1))
    expect(api.calls[0]!.body).toEqual({
      message: "TypeError: deal.stage is undefined",
      stack: error.stack,
      component_stack: "\n    at DealCard",
      path: "/reset-password",
    })
    expect(JSON.stringify(api.calls[0]!.body)).not.toContain("dfp_secret")
  })

  it("leaves out what isn't a bug, repeats, and anything past five", async () => {
    const api = mockApi({ "POST /api/v1/client-errors": { status: 204 } })
    errors.reportError(new TypeError("Failed to fetch")) // the network
    errors.reportError(new TypeError("Importing a module script failed.")) // a deploy
    errors.reportError({ status: 404, statusText: "Not Found" }) // a route that doesn't exist
    for (let i = 0; i < 8; i++) errors.reportError(new Error(`bug ${i % 7}`))
    errors.reportError(new Error("bug 0"))
    await vi.waitFor(() => expect(api.calls).toHaveLength(5))
    expect(api.calls.map((c) => (c.body as { message: string }).message)).toEqual(
      [0, 1, 2, 3, 4].map((i) => `Error: bug ${i}`),
    )
  })

  it("never throws, even when the report can't be sent", async () => {
    const api = mockApi({
      "POST /api/v1/client-errors": () => Promise.reject(new Error("offline")),
    })
    expect(() => errors.reportError(new Error("bug"))).not.toThrow()
    await vi.waitFor(() => expect(api.calls).toHaveLength(1))
  })
})
