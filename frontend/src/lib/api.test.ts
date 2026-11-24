import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { apiErrorMessage, invalidate } from "@/lib/api"

describe("apiErrorMessage", () => {
  it("uses the API's own sentence", () => {
    expect(apiErrorMessage({ detail: "You can't delete the last stage" })).toBe(
      "You can't delete the last stage",
    )
  })

  it("names the field a validation error is about", () => {
    const error = { detail: [{ loc: ["body", "expected_close_date"], msg: "Invalid date" }] }
    expect(apiErrorMessage(error)).toBe("expected close date: Invalid date")
  })

  it("falls back when there's nothing readable", () => {
    expect(apiErrorMessage({ detail: [] })).toBe("Something went wrong")
    expect(apiErrorMessage(undefined, "Couldn't save")).toBe("Couldn't save")
    expect(apiErrorMessage(new TypeError("Failed to fetch"))).toBe("Failed to fetch")
  })
})

describe("invalidate", () => {
  it("refetches the named endpoints, whatever their parameters, and nothing else", async () => {
    const client = new QueryClient()
    const key = (id: string, path?: object) => [{ _id: id, ...(path && { path }) }]
    client.setQueryData(key("dealsReadDeal", { deal_id: 1 }), {})
    client.setQueryData(key("dealsReadDeal", { deal_id: 2 }), {})
    client.setQueryData(key("usersReadMe"), {})

    await invalidate(client, "dealsReadDeal")

    const stale = client
      .getQueryCache()
      .getAll()
      .filter((q) => q.isStale())
      .map((q) => q.queryKey)
    expect(stale).toEqual([
      key("dealsReadDeal", { deal_id: 1 }),
      key("dealsReadDeal", { deal_id: 2 }),
    ])
  })
})
