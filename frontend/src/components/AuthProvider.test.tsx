import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { usersReadMe } from "@/client/sdk.gen"
import { AuthProvider } from "@/components/AuthProvider"
import { useAuth } from "@/lib/auth"
import { mockApi } from "@/test/api"

const OWNER = {
  id: 1,
  email: "owner@example.com",
  full_name: "Asha",
  role: "owner",
  is_active: true,
}

function WhoIsSignedIn() {
  const { user, isLoading, login, logout } = useAuth()
  if (isLoading) return <p>Loading</p>
  return (
    <div>
      <p>{user ? `Signed in as ${user.email}` : "Signed out"}</p>
      <button
        onClick={() =>
          login("owner@example.com", "wrong").catch((e: Error) => {
            document.title = e.message
          })
        }
      >
        Sign in
      </button>
      <button onClick={() => void logout()}>Sign out</button>
    </div>
  )
}

function renderAuth() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <WhoIsSignedIn />
      </AuthProvider>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe("AuthProvider", () => {
  it("asks the API who's signed in (the session is an httpOnly cookie)", async () => {
    mockApi({ "GET /api/v1/users/me": { json: OWNER } })
    renderAuth()
    expect(await screen.findByText("Signed in as owner@example.com")).toBeInTheDocument()
  })

  it("passes on the API's reason a sign-in failed", async () => {
    const api = mockApi({
      "GET /api/v1/users/me": { status: 401, json: { detail: "Not signed in" } },
      "POST /api/v1/login/access-token": {
        status: 429,
        json: { detail: "Too many failed sign-ins. Try again in 15 minutes." },
      },
    })
    const user = renderAuth()
    await user.click(await screen.findByRole("button", { name: "Sign in" }))
    await waitFor(() =>
      expect(document.title).toBe("Too many failed sign-ins. Try again in 15 minutes."),
    )
    const signIn = api.calls.find((c) => c.path.endsWith("/access-token"))!
    expect(signIn.body).toBe("username=owner%40example.com&password=wrong")
    expect(screen.getByText("Signed out")).toBeInTheDocument()
  })

  it("notices when any API call finds the session has ended", async () => {
    let me = { status: 200, json: OWNER as unknown }
    mockApi({
      "GET /api/v1/users/me": () => Response.json(me.json, { status: me.status }),
      "GET /api/v1/deals": { status: 401, json: { detail: "Could not validate credentials" } },
    })
    renderAuth()
    await screen.findByText("Signed in as owner@example.com")

    me = { status: 401, json: { detail: "Could not validate credentials" } } // signed out elsewhere
    await (await import("@/client/sdk.gen")).dealsListDeals()
    expect(await screen.findByText("Signed out")).toBeInTheDocument()
  })

  it("sends the CSRF header that the API requires for changes", async () => {
    const api = mockApi({ "GET /api/v1/users/me": { json: OWNER } })
    await usersReadMe()
    expect(api.calls[0]!.headers.get("X-Dealflow-CSRF")).toBe("1")
  })
})
