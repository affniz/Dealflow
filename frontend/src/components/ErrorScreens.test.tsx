import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ErrorBoundary } from "@/components/ErrorScreens"
import { mockApi } from "@/test/api"

function Broken({ error }: { error: Error }): never {
  throw error
}

describe("ErrorBoundary", () => {
  it("shows a message with a Reload button instead of a blank screen, and reports it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {}) // React logs the error too
    const api = mockApi({ "POST /api/v1/client-errors": { status: 204 } })
    render(
      <ErrorBoundary compact>
        <Broken error={new TypeError("proposals.map is not a function")} />
      </ErrorBoundary>,
    )
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("Something went wrong")
    expect(alert).toHaveTextContent("proposals.map is not a function")
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument()
    await vi.waitFor(() => expect(api.calls).toHaveLength(1))
    expect(api.calls[0]!.body).toMatchObject({
      message: "TypeError: proposals.map is not a function",
    })
  })

  it("says the app was updated when a page's file is gone, and doesn't report that", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {})
    const api = mockApi({})
    render(
      <ErrorBoundary compact>
        <Broken error={new TypeError("Failed to fetch dynamically imported module: /a.js")} />
      </ErrorBoundary>,
    )
    expect(screen.getByRole("alert")).toHaveTextContent("Dealflow has been updated")
    expect(screen.getByRole("alert")).not.toHaveTextContent("/a.js")
    await new Promise((r) => setTimeout(r, 20))
    expect(api.calls).toHaveLength(0)
  })

  it("shows its children when nothing is wrong", () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText("All good")).toBeInTheDocument()
  })
})
