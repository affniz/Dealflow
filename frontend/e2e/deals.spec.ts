import { USERS, expect, signInAs, test, unique } from "./fixtures.ts"

test.beforeEach(async ({ page }) => {
  await signInAs(page, USERS.admin)
})

test("add a deal, move it along, and win it", async ({ page }) => {
  const title = unique("Cold storage upgrade")
  await page.goto("/")
  await page.getByRole("button", { name: "New deal" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("Title").fill(title)
  await dialog.getByLabel("Value (₹)").fill("425000")
  await dialog.getByRole("button", { name: "Add deal" }).click()
  await expect(dialog).toBeHidden()

  const lead = page.getByRole("region", { name: "Lead" })
  await lead.getByRole("link", { name: title }).click()
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.getByText("₹4,25,000")).toBeVisible()

  const stages = page.getByRole("list", { name: "Stage" })
  await stages.getByRole("button", { name: /Proposal/ }).click()
  await expect(stages.getByRole("button", { name: /Proposal/ })).toHaveAttribute(
    "aria-current",
    "step",
  )

  await page.getByRole("button", { name: "Won" }).click()
  await expect(page.getByText("Won", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible()
})

test("drag a deal to the next stage on the board", async ({ page }) => {
  await page.goto("/")
  const card = page.getByRole("region", { name: "Lead" }).getByText("Loyalty programme revamp")
  const target = page.getByRole("region", { name: "Qualified" })
  await expect(card).toBeVisible()

  // dnd-kit starts a drag after the pointer moves a few pixels, so move in steps
  const from = (await card.boundingBox())!
  const to = (await target.boundingBox())!
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(from.x + from.width / 2 + 20, from.y + from.height / 2, { steps: 5 })
  await page.mouse.move(to.x + to.width / 2, to.y + 120, { steps: 15 })
  await page.mouse.up()

  await expect(target.getByText("Loyalty programme revamp")).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole("region", { name: "Qualified" }).getByText("Loyalty programme revamp"),
  ).toBeVisible()
})

test("a lost deal needs a reason and can be reopened", async ({ page }) => {
  const title = unique("Kiosk rollout")
  await page.goto("/")
  await page.getByRole("button", { name: "New deal" }).click()
  await page.getByRole("dialog").getByLabel("Title").fill(title)
  await page.getByRole("dialog").getByRole("button", { name: "Add deal" }).click()
  await page.getByRole("region", { name: "Lead" }).getByRole("link", { name: title }).click()

  await page.getByRole("button", { name: "Lost" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("Reason").selectOption({ index: 1 })
  await dialog.getByLabel("Note (optional)").fill("Budget moved to next year")
  await dialog.getByRole("button", { name: /lost/i }).click()
  await expect(page.getByText("Lost", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "Reopen" }).click()
  await expect(page.getByRole("button", { name: "Won" })).toBeVisible()
})
