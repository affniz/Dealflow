import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { ContactMatch, ContactPublic, UserPublic } from "@/client/types.gen"
import { ContactSheet } from "@/components/records/ContactSheet"
import { AuthContext } from "@/lib/auth"
import { mockApi } from "@/test/api"
import { renderWithApp } from "@/test/render"

const ARJUN = { id: 7, email: "arjun@example.com", role: "agent" } as UserPublic

const PRIYA: ContactMatch = {
  id: 3,
  name: "Priya Shah",
  job_title: null,
  email: "priya@zenith.in",
  phone: null,
  company: { id: 2, name: "Zenith" },
  owner: { id: 8, name: "Sana" },
  reasons: ["email"],
}

const saved = { id: 11, first_name: "Priya" } as ContactPublic

function renderSheet(duplicates: ContactMatch[] | { status: number }) {
  const api = mockApi({
    "GET /api/v1/companies": { json: { data: [], count: 0 } },
    "POST /api/v1/contacts/duplicates":
      "status" in duplicates ? { ...duplicates, json: { detail: "Down" } } : { json: duplicates },
    "POST /api/v1/contacts": { status: 201, json: saved },
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
      <ContactSheet open onClose={() => {}} />
    </AuthContext.Provider>,
  )
  return { ...result, api }
}

const posted = (api: ReturnType<typeof mockApi>) =>
  api.calls.filter((c) => c.method === "POST").map((c) => c.path)

describe("ContactSheet", () => {
  it("asks before adding someone who may already be there", async () => {
    const { user, api } = renderSheet([PRIYA])
    await user.type(screen.getByLabelText("First name"), "Priya")
    await user.type(screen.getByLabelText("Email"), "priya@zenith.in")
    await user.click(screen.getByRole("button", { name: "Add contact" }))

    const warning = await screen.findByRole("alert")
    expect(warning).toHaveTextContent("This person may already be in Dealflow")
    expect(warning).toHaveTextContent("same email · Sana's contact")
    expect(screen.getByRole("link", { name: "Priya Shah" })).toHaveAttribute("href", "/contacts/3")
    expect(posted(api)).toEqual(["/api/v1/contacts/duplicates"]) // nothing added yet
    expect(api.calls[api.calls.length - 1]!.body).toMatchObject({
      first_name: "Priya",
      email: "priya@zenith.in",
      exclude_id: null,
    })

    await user.click(screen.getByRole("button", { name: "Add anyway" }))
    expect(await screen.findByRole("status")).toHaveTextContent("Added Priya")
    expect(posted(api)).toEqual(["/api/v1/contacts/duplicates", "/api/v1/contacts"])
  })

  it("checks again after the details change", async () => {
    const { user, api } = renderSheet([PRIYA])
    await user.type(screen.getByLabelText("First name"), "Priya")
    await user.click(screen.getByRole("button", { name: "Add contact" }))
    await screen.findByRole("alert")

    await user.type(screen.getByLabelText("Last name"), "S")
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Add contact" }))
    await screen.findByRole("alert")
    expect(posted(api)).toEqual(["/api/v1/contacts/duplicates", "/api/v1/contacts/duplicates"])
  })

  it("adds straight away when nobody matches, or when the check fails", async () => {
    for (const reply of [[], { status: 500 }]) {
      const { user, api, unmount } = renderSheet(reply)
      await user.type(screen.getByLabelText("First name"), "Ravi")
      await user.click(screen.getByRole("button", { name: "Add contact" }))
      expect(await screen.findByRole("status")).toHaveTextContent("Added Priya")
      expect(posted(api)).toEqual(["/api/v1/contacts/duplicates", "/api/v1/contacts"])
      unmount()
    }
  })
})
