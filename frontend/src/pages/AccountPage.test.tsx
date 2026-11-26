import { screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { ApiTokenCreated, ApiTokenPublic, UserPublic } from "@/client/types.gen"
import { AccountPage } from "@/pages/AccountPage"
import { AuthContext } from "@/lib/auth"
import { mockApi } from "@/test/api"
import { renderWithApp } from "@/test/render"

const ARJUN = { id: 7, email: "arjun@example.com", role: "agent" } as UserPublic
const DAY = 24 * 60 * 60 * 1000
const inDays = (days: number) => new Date(Date.now() + days * DAY).toISOString()

const token = (over: Partial<ApiTokenPublic>): ApiTokenPublic => ({
  id: 1,
  name: "Claude Code",
  prefix: "dfp_abcdef",
  scope: "read",
  created_at: inDays(-10),
  expires_at: inDays(80),
  last_used_at: null,
  ...over,
})

function renderPage(tokens: ApiTokenPublic[], user: UserPublic = ARJUN) {
  const created: ApiTokenCreated = {
    ...token({ id: 9, name: "Laptop", expires_at: inDays(30) }),
    token: "dfp_secret",
  }
  const api = mockApi({
    "GET /api/v1/users/me/tokens": { json: tokens },
    "GET /api/v1/config": { json: {} },
    "POST /api/v1/users/me/tokens": { status: 201, json: created },
  })
  const auth = {
    user,
    isLoading: false,
    isAuthenticated: true,
    login: async () => {},
    logout: async () => {},
  }
  const result = renderWithApp(
    <AuthContext.Provider value={auth}>
      <AccountPage />
    </AuthContext.Provider>,
  )
  return { ...result, api }
}

describe("Connect Claude", () => {
  it("shows each token's access and when it expires", async () => {
    renderPage([
      token({ id: 1, name: "Reader" }),
      token({ id: 2, name: "Helper", scope: "suggest", expires_at: inDays(3) }),
      token({ id: 3, name: "Old laptop", expires_at: inDays(-2) }),
    ])
    const row = async (name: string) => (await screen.findByText(name)).closest("li")!

    expect(await row("Reader")).toHaveTextContent("Read only")
    expect(await row("Reader")).toHaveTextContent("Expires in 3 months")
    const helper = await row("Helper")
    expect(helper).toHaveTextContent("Can suggest")
    expect(helper).toHaveTextContent("Expires in 3 days")
    // its last week: picked out in amber
    expect(within(helper).getByText("in 3 days").parentElement).toHaveClass("text-amber-700")
    expect(await row("Old laptop")).toHaveTextContent(
      "Expired 2 days ago. Revoke it, and create a new one if you still need it.",
    )
  })

  it("creates read-only tokens for 90 days unless asked otherwise", async () => {
    const { user, api } = renderPage([])
    await user.click(await screen.findByRole("button", { name: "Create token" }))
    const dialog = screen.getByRole("dialog", { name: "Create a token" })
    expect(within(dialog).getByRole("radio", { name: /Read only/ })).toBeChecked()
    expect(within(dialog).getByLabelText("Expires")).toHaveValue("90")

    await user.click(within(dialog).getByRole("radio", { name: /Read and suggest changes/ }))
    await user.selectOptions(within(dialog).getByLabelText("Expires"), "In 30 days")
    await user.click(within(dialog).getByRole("button", { name: "Create token" }))

    expect(await screen.findByRole("dialog", { name: "Your new token" })).toHaveTextContent(
      "Read only. Works until",
    )
    const sent = api.calls.find((c) => c.method === "POST")!
    expect(sent.body).toEqual({ name: "Claude Code", scope: "suggest", expires_in_days: 30 })
  })

  it("doesn't offer viewers a token that suggests changes", async () => {
    const { user } = renderPage([], { ...ARJUN, role: "viewer" })
    await user.click(await screen.findByRole("button", { name: "Create token" }))
    const dialog = screen.getByRole("dialog", { name: "Create a token" })
    expect(within(dialog).getByRole("radio", { name: /Read only/ })).toBeChecked()
    expect(within(dialog).getByRole("radio", { name: /Read and suggest changes/ })).toBeDisabled()
    expect(dialog).toHaveTextContent("Viewers can't suggest changes.")
  })
})
