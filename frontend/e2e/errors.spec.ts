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
  await page.goto("/dashboard")
  await expect(page.getByRole("alert")).toContainText("Something went wrong")
  await page.getByRole("link", { name: "Pipeline" }).first().click() // the rest of the app still works
  await expect(page.getByRole("region", { name: "Lead" })).toBeVisible()
})
