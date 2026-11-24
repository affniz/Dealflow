import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { AgentProposalPublic } from "@/client/types.gen"
import { ProposalCard } from "@/components/copilot/ProposalCard"
import { mockApi } from "@/test/api"
import { renderWithApp } from "@/test/render"

const proposal = (overrides: Partial<AgentProposalPublic> = {}) =>
  ({
    id: 5,
    status: "pending",
    source: "pipeline_agent",
    summary: "Log a follow-up call with Priya",
    rationale: "No contact in 21 days",
    deal: { id: 9, name: "Annual licence" },
    error: null,
    ...overrides,
  }) as AgentProposalPublic

describe("ProposalCard", () => {
  it("applies the change only when someone approves it", async () => {
    const api = mockApi({
      "POST /api/v1/proposals/5/approve": { json: proposal({ status: "approved" }) },
    })
    const { user } = renderWithApp(<ProposalCard proposal={proposal()} canDecide showDeal />)
    expect(screen.getByText("Pipeline agent suggestion")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Annual licence" })).toHaveAttribute("href", "/deals/9")
    expect(api.calls).toHaveLength(0)

    await user.click(screen.getByRole("button", { name: "Approve" }))
    expect(await screen.findByRole("status")).toHaveTextContent("Approved and applied")
    expect(api.calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /api/v1/proposals/5/approve",
    ])
  })

  it("says why when the change couldn't be applied", async () => {
    mockApi({
      "POST /api/v1/proposals/5/approve": {
        json: proposal({ status: "failed", error: "The deal was deleted" }),
      },
    })
    const { user } = renderWithApp(<ProposalCard proposal={proposal()} canDecide />)
    await user.click(screen.getByRole("button", { name: "Approve" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't apply it: The deal was deleted",
    )
  })

  it("shows the API's answer when approving is refused", async () => {
    mockApi({
      "POST /api/v1/proposals/5/reject": {
        status: 409,
        json: { detail: "Someone already decided on this suggestion" },
      },
    })
    const { user } = renderWithApp(<ProposalCard proposal={proposal()} canDecide />)
    await user.click(screen.getByRole("button", { name: "Reject" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone already decided on this suggestion",
    )
  })

  it("has no buttons for someone who can't decide, or once it's decided", () => {
    renderWithApp(<ProposalCard proposal={proposal()} canDecide={false} />)
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("shows how it ended", () => {
    renderWithApp(<ProposalCard proposal={proposal({ status: "approved" })} canDecide />)
    expect(screen.getByText("Applied")).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("says why a suggestion expired", () => {
    const reason = "Nobody decided on this within 7 days, so it expired"
    renderWithApp(
      <ProposalCard proposal={proposal({ status: "expired", error: reason })} canDecide />,
    )
    expect(screen.getByText("expired")).toBeInTheDocument()
    expect(screen.getByText(reason)).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })
})
