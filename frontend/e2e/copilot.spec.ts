import { type Page } from "@playwright/test"

import { USERS, expect, signInAs, test, unique } from "./fixtures.ts"

// The API runs Copilot with a scripted stand-in for Claude (backend/app/agent/scripted.py): it
// calls the real tools on the demo data, so these check the chat, the tools' permissions and
// the approval cards end to end, without calling Claude.

async function openCopilot(page: Page) {
  await page.getByRole("button", { name: "Ask Copilot" }).click()
  return page.getByRole("complementary", { name: "Copilot" })
}

async function ask(page: Page, text: string) {
  const copilot = await openCopilot(page)
  await copilot.getByLabel("Message Copilot").fill(text)
  await copilot.getByRole("button", { name: "Send" }).click()
  return copilot
}

test("Copilot answers from the agent's own deals, and the chat is there next time", async ({
  page,
}) => {
  await signInAs(page, USERS.agent)
  await page.goto("/")
  const copilot = await openCopilot(page)
  await copilot
    .getByRole("button", { name: "Which deals are stalled, and what should I do about them?" })
    .click()

  await expect(copilot.getByText("These deals are stalled:")).toBeVisible()
  await expect(copilot.getByText("Searched deals", { exact: true })).toBeVisible()
  await expect(copilot.getByText("Supplier portal")).toBeVisible() // Arjun's
  await expect(copilot.getByText("Clinic scheduling suite")).toHaveCount(0) // Sana's
  await expect(copilot.getByRole("status")).toHaveCount(0) // done working

  await page.reload()
  const again = await openCopilot(page)
  await expect(again.getByText("These deals are stalled:")).toBeVisible()
})

/** A deal of the signed-in user's in a stage of the default pipeline, named for this run only. */
async function dealIn(page: Page, stageName: string, title: string) {
  const res = await page.request.get("/api/v1/pipelines")
  const [pipeline] = await res.json()
  const stage = pipeline.stages.find((s: { name: string }) => s.name === stageName)
  const deal = await page.request.post("/api/v1/deals", {
    data: { title, value: 100000, stage_id: stage.id },
    headers: { "X-Dealflow-CSRF": "1" }, // as the app sends with every request
  })
  expect(deal.ok(), await deal.text()).toBeTruthy()
}

test("approving Copilot's suggestion moves the deal; rejecting it doesn't", async ({ page }) => {
  await signInAs(page, USERS.agent)
  const approved = unique("Copilot pilot")
  const rejected = unique("Copilot licence")
  await dealIn(page, "Qualified", approved)
  await dealIn(page, "Proposal", rejected)
  await page.goto("/")
  const copilot = await ask(page, `Move ${approved} to Proposal`)

  await expect(copilot.getByText(`Move “${approved}” from Qualified to Proposal`)).toBeVisible()
  await expect(copilot.getByText("Nothing changes until you approve it.")).toBeVisible()
  // nothing has moved yet
  await expect(page.getByRole("region", { name: "Qualified" }).getByText(approved)).toBeVisible()

  await copilot.getByRole("button", { name: "Approve" }).click()
  await expect(copilot.getByText("Applied")).toBeVisible()
  await expect(page.getByRole("region", { name: "Proposal" }).getByText(approved)).toBeVisible()

  await copilot.getByLabel("Message Copilot").fill(`Move ${rejected} to Negotiation`)
  await copilot.getByRole("button", { name: "Send" }).click()
  await expect(copilot.getByText(`Move “${rejected}” from Proposal to Negotiation`)).toBeVisible()
  await copilot.getByRole("button", { name: "Reject" }).click()
  await expect(copilot.getByText("rejected", { exact: true })).toBeVisible()
  await expect(copilot.getByRole("button", { name: "Approve" })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole("region", { name: "Proposal" }).getByText(rejected)).toBeVisible()
})

test("a viewer can ask Copilot, but it can't suggest changes for them", async ({ page }) => {
  await signInAs(page, USERS.viewer)
  await page.goto("/")
  const copilot = await openCopilot(page)
  await expect(copilot.getByText("As a viewer you can't make changes.")).toBeVisible()

  await copilot.getByLabel("Message Copilot").fill("Move Fleet tracking rollout to Lead")
  await copilot.getByRole("button", { name: "Send" }).click()
  await expect(copilot.getByText(/I couldn't suggest that: This user is a viewer/)).toBeVisible()
  await expect(copilot.getByRole("button", { name: "Approve" })).toHaveCount(0)
})

test("when Claude can't be reached, the message comes back to send again", async ({ page }) => {
  await signInAs(page, USERS.agent)
  await page.goto("/")
  const copilot = await ask(page, "This one will fail")

  await expect(copilot.getByRole("alert")).toHaveText(
    "Copilot couldn't reach Claude just now. Try again.",
  )
  await expect(copilot.getByLabel("Message Copilot")).toHaveValue("This one will fail")
  await expect(copilot.getByRole("button", { name: "Send" })).toBeEnabled()
})
