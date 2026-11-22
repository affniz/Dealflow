import { USERS, expect, signInAs, test, unique } from "./fixtures.ts"

test.beforeEach(async ({ page }) => {
  await signInAs(page, USERS.admin)
})

test("the dashboard shows the pipeline and follows its filters", async ({ page }) => {
  await page.goto("/dashboard")
  await expect(page.getByText("Open pipeline", { exact: true })).toBeVisible()
  await expect(page.getByText("Win rate", { exact: true })).toBeVisible()
  const byStage = page.getByRole("list", { name: "Open pipeline value by stage" })
  await expect(byStage.getByRole("listitem")).toHaveCount(4)

  await page.getByLabel("Period").selectOption("30")
  await expect(page).toHaveURL(/period=30/)
})

test("a new lost reason is offered when a deal is lost", async ({ page }) => {
  const reason = unique("Chose an in-house build")
  await page.goto("/settings?tab=lost-reasons")
  await page.getByLabel("New lost reason").fill(reason)
  await page.getByRole("button", { name: "Add" }).click()
  await expect(page.getByLabel(`Name of “${reason}”`)).toBeVisible()

  await page.goto("/")
  await page.getByRole("link", { name: "Supplier portal" }).click()
  await page.getByRole("button", { name: "Lost" }).click()
  await expect(
    page.getByRole("dialog").getByLabel("Reason").locator("option", { hasText: reason }),
  ).toHaveCount(1)
})

test("connect Claude: create a token, use it over MCP, revoke it", async ({ page }) => {
  await page.goto("/account")
  await page.getByRole("button", { name: "Create token" }).click()
  const dialog = page.getByRole("dialog", { name: "Create a token" })
  await dialog.getByLabel("Name").fill("e2e")
  await dialog.getByRole("button", { name: "Create token" }).click()
  const token = (await page.getByLabel("Token", { exact: true }).innerText()).trim()
  expect(token).toMatch(/^dfp_/)
  await page.getByRole("button", { name: "Done" }).click()

  const call = (t: string) =>
    page.request.post("/mcp", {
      headers: {
        Authorization: `Bearer ${t}`,
        Accept: "application/json, text/event-stream",
      },
      data: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
    })
  const listed = await call(token)
  expect(listed.status()).toBe(200)
  expect(JSON.stringify(await listed.json())).toContain("search_deals")

  await page.getByRole("button", { name: "Revoke" }).click()
  await page.getByRole("button", { name: "Revoke token" }).click()
  await expect(page.getByText("No tokens yet")).toBeVisible()
  expect((await call(token)).status()).toBe(401)
})

test("an admin's reset link lets someone choose a new password", async ({ page, browser }) => {
  const email = `reset-${Date.now().toString(36)}@example.com`
  const made = await page.request.post("/api/v1/users", {
    headers: { "X-Dealflow-CSRF": "1" },
    data: { email, full_name: "Riya Reset", password: "first-password-1", role: "agent" },
  })
  expect(made.ok(), await made.text()).toBeTruthy()

  await page.goto("/settings")
  await page
    .getByRole("listitem")
    .filter({ hasText: email })
    .getByRole("button", { name: "Reset link" })
    .click()
  const link = (await page.getByLabel("Link", { exact: true }).innerText()).trim()
  expect(link).toMatch(/\/reset-password#dfp_/)
  await page.getByRole("button", { name: "Done" }).click()

  // they open it in their own browser
  const theirs = await browser.newPage()
  await theirs.goto(link)
  await expect(theirs).toHaveURL(/\/reset-password$/) // the secret leaves the address bar
  await theirs.getByLabel("New password", { exact: true }).fill("second-password-2")
  await theirs.getByLabel("New password again").fill("second-password-2")
  await theirs.getByRole("button", { name: "Set new password" }).click()
  await expect(theirs.getByRole("status")).toContainText("Password changed")

  await theirs.getByRole("link", { name: "Back to sign in" }).click()
  await expect(theirs.getByRole("heading", { name: "Sign in" })).toBeVisible()
  await theirs.getByLabel("Email").fill(email)
  await theirs.getByLabel("Password").fill("second-password-2")
  await theirs.getByRole("button", { name: "Sign in" }).click()
  await expect(theirs.getByRole("link", { name: "Riya Reset" })).toBeVisible()
  await theirs.close()
})
