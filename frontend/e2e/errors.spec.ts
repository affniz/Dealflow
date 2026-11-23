import { USERS, expect, signInAs, test } from "./fixtures.ts"

test.beforeEach(async ({ page }) => {
  await signInAs(page, USERS.admin)
})

test("a page whose code can't be downloaded says so, inside the app", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("region", { name: "Lead" })).toBeVisible()
  // as after a deploy: the page's file from the old build is gone
  await page.route("**/src/pages/DashboardPage.tsx*", (route) => route.abort())
  await page.getByRole("link", { name: "Dashboard" }).first().click()

  await expect(page.getByRole("alert")).toContainText("Dealflow has been updated")
  await expect(page.getByRole("link", { name: "Pipeline" }).first()).toBeVisible() // navigation still works

  await page.unroute("**/src/pages/DashboardPage.tsx*")
  await page.getByRole("button", { name: "Reload" }).click()
  await expect(page.getByText("Open pipeline", { exact: true })).toBeVisible()
})

test("a page that crashes shows an error instead of a blank screen", async ({ page }) => {
  // an answer the page doesn't expect
  await page.route("**/api/v1/dashboard/pipeline/*", (route) =>
    route.fulfill({ json: { unexpected: true } }),
  )
  const report = page.waitForRequest("**/api/v1/client-errors")
  await page.goto("/dashboard")
  await expect(page.getByRole("alert")).toContainText("Something went wrong")
  // and the server hears about it
  const sent = (await report).postDataJSON()
  expect(sent.path).toBe("/dashboard")
  expect(sent.message).toMatch(/^TypeError: /)
  await page.getByRole("link", { name: "Pipeline" }).first().click() // the rest of the app still works
  await expect(page.getByRole("region", { name: "Lead" })).toBeVisible()
})

test("admins see when a background job is failing", async ({ page }) => {
  await page.goto("/settings?tab=system")
  await expect(page.getByText("Everything is working.")).toBeVisible()
  await expect(page.getByText("Stalled-deal check")).toBeVisible()

  const problem = "Trash cleanup failed on 23 Nov, 09:00 IST: RuntimeError: disk full"
  await page.route("**/api/v1/system/status", async (route) => {
    const status = await (await route.fetch()).json()
    await route.fulfill({ json: { ...status, problems: [problem] } })
  })
  await page.goto("/")
  const banner = page.getByRole("status").filter({ hasText: problem })
  await expect(banner).toBeVisible()
  await banner.getByRole("link", { name: "See system status" }).click()
  await expect(page.getByRole("list", { name: "Needs attention" })).toContainText(problem)
  await expect(banner).toBeHidden() // not repeated on the page that lists it
})
