import { PASSWORD, USERS, expect, test } from "./fixtures.ts"

test("signing in, a wrong password, and signing out", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()

  await page.getByLabel("Email").fill(USERS.admin)
  await page.getByLabel("Password").fill("not-the-password")
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("alert")).toBeVisible()

  await page.getByLabel("Password").fill(PASSWORD)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("region", { name: "Lead" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Meera Iyer" })).toBeVisible()

  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
})
