import { USERS, expect, signInAs, test } from "./fixtures.ts"

test("an agent sees only their own deals", async ({ page, request }) => {
  await signInAs(page, USERS.agent)
  await page.goto("/")
  await expect(page.getByText("Fleet tracking rollout")).toBeVisible() // Arjun's
  await expect(page.getByText("Clinic scheduling suite")).toHaveCount(0) // Sana's

  // and can't open a teammate's deal by its address (looked up as her, on a separate client
  // so the page keeps Arjun's session cookie)
  const sanas = await request.post("/api/v1/login/access-token", {
    form: { username: USERS.otherAgent, password: "demo-password" },
  })
  const token = ((await sanas.json()) as { access_token: string }).access_token
  const deals = await request.get("/api/v1/deals?q=Clinic", {
    headers: { Authorization: `Bearer ${token}` },
  })
  const id = ((await deals.json()) as { data: { id: number }[] }).data[0]!.id
  await page.goto(`/deals/${id}`)
  await expect(page.getByText(/not found|doesn't exist|isn't available/i)).toBeVisible()
})

test("a viewer can look but not change anything", async ({ page }) => {
  await signInAs(page, USERS.viewer)
  await page.goto("/")
  await expect(page.getByText("Clinic scheduling suite")).toBeVisible() // sees the whole team
  await expect(page.getByRole("button", { name: "New deal" })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Settings" })).toHaveCount(0)

  await page.getByRole("link", { name: "Fleet tracking rollout" }).click()
  await expect(page.getByRole("heading", { name: "Fleet tracking rollout" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Won" })).toHaveCount(0)
})

test("only admins reach settings", async ({ page }) => {
  await signInAs(page, USERS.agent)
  await page.goto("/settings")
  await expect(page).toHaveURL(/\/$/)
})
