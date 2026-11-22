import { PASSWORD, USERS, expect, signInAs, test } from "./fixtures.ts"

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
  // the session is an httpOnly cookie: it survives a reload, and page scripts can't see it
  await page.reload()
  await expect(page.getByRole("link", { name: "Meera Iyer" })).toBeVisible()
  expect(await page.evaluate(() => [document.cookie, JSON.stringify(localStorage)])).not.toContain(
    expect.stringMatching(/ey[\w-]+\.ey/),
  )

  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
})

test("signing out everywhere ends every session", async ({ page, request }) => {
  await signInAs(page, USERS.viewer)
  // a second sign-in elsewhere: a script with a bearer token
  const other = await request.post("/api/v1/login/access-token", {
    form: { username: USERS.viewer, password: PASSWORD },
  })
  const auth = {
    Authorization: `Bearer ${((await other.json()) as { access_token: string }).access_token}`,
  }
  expect((await request.get("/api/v1/users/me", { headers: auth })).status()).toBe(200)

  await page.goto("/account")
  await page.getByRole("button", { name: "Sign out everywhere" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Sign out everywhere" }).click()
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
  expect((await request.get("/api/v1/users/me", { headers: auth })).status()).toBe(401)
})

test("forgot your password? asks for an email", async ({ page }) => {
  await page.goto("/login")
  await page.getByRole("link", { name: "Forgot your password?" }).click()
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible()
  await page.getByLabel("Email").fill(USERS.agent)
  await page.getByRole("button", { name: "Email me a link" }).click()
  // the same answer whether or not the email has an account
  await expect(page.getByRole("status")).toContainText("If that email has an account")
})
