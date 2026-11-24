import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { ConversationView, UserPublic } from "@/client/types.gen"
import { CopilotPanel } from "@/components/copilot/CopilotPanel"
import { AuthContext } from "@/lib/auth"
import { mockApi } from "@/test/api"
import { renderWithApp } from "@/test/render"

const ARJUN = { id: 7, email: "arjun@example.com", role: "agent" } as UserPublic

function view(overrides: Partial<ConversationView>): ConversationView {
  return {
    id: 3,
    title: "How is Fleet tracking?",
    items: [],
    proposals: [],
    updated_at: "2026-11-24T10:00:00Z",
    running: false,
    failure: null,
    ...overrides,
  }
}

const ASKED = { kind: "user" as const, text: "How is Fleet tracking?" }

function renderPanel(conversation: () => ConversationView, sent: ConversationView) {
  const api = mockApi({
    "GET /api/v1/copilot/status": {
      json: { enabled: true, review_hour: 7, timezone: "Asia/Kolkata" },
    },
    "GET /api/v1/usage/me": { json: { cost_usd: "0", budget_usd: null } },
    "GET /api/v1/settings/ai": { status: 403, json: { detail: "Admins only" } },
    "POST /api/v1/copilot/messages": { status: 202, json: sent },
    "GET /api/v1/copilot/conversations": { json: [] },
    "GET /api/v1/copilot/conversations/3": () => Response.json(conversation()),
    "GET /api/v1/proposals": { json: [] },
  })
  const auth = {
    user: ARJUN,
    isLoading: false,
    isAuthenticated: true,
    login: async () => {},
    logout: async () => {},
  }
  const result = renderWithApp(
    <AuthContext.Provider value={auth}>
      <CopilotPanel open onClose={() => {}} />
    </AuthContext.Provider>,
  )
  return { ...result, api }
}

describe("CopilotPanel", () => {
  it("shows each step while Copilot works, then the answer", async () => {
    let polls = 0
    const { user } = renderPanel(
      () => {
        polls += 1
        return polls === 1
          ? view({ running: true, items: [ASKED, { kind: "step", text: "Read “Fleet tracking”" }] })
          : view({
              items: [
                ASKED,
                { kind: "step", text: "Read “Fleet tracking”" },
                { kind: "assistant", text: "Priya is waiting on the revised quote." },
              ],
            })
      },
      view({ running: true, items: [ASKED] }),
    )

    await user.type(screen.getByLabelText("Message Copilot"), "How is Fleet tracking?{Enter}")
    expect(await screen.findByText("Working on it…")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled() // one message at a time
    expect(await screen.findByText("Read “Fleet tracking”")).toBeInTheDocument()
    expect(
      await screen.findByText("Priya is waiting on the revised quote.", {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.queryByText("Working on it…")).not.toBeInTheDocument()
  })

  it("says why an answer failed and puts the message back to send again", async () => {
    let polls = 0
    const { user } = renderPanel(
      () => {
        polls += 1
        return polls === 1
          ? view({ running: true, items: [ASKED] })
          : view({
              failure: {
                message: "Copilot couldn't reach Claude just now. Try again.",
                text: "How is Fleet tracking?",
              },
            })
      },
      view({ running: true, items: [ASKED] }),
    )

    const box = screen.getByLabelText("Message Copilot")
    await user.type(box, "How is Fleet tracking?{Enter}")
    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent(
      "Copilot couldn't reach Claude just now. Try again.",
    )
    await waitFor(() => expect(box).toHaveValue("How is Fleet tracking?"))
  })
})
