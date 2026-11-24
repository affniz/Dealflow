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

test("an agent sees the team's companies but changes only their own", async ({ page }) => {
  await signInAs(page, USERS.agent)
  await page.goto("/companies")
  await page.getByRole("link", { name: "Nimbus Health" }).click() // Sana's account
  await expect(page.getByRole("heading", { name: "Nimbus Health" })).toBeVisible()
  await expect(page.getByText("Sana Qureshi")).toBeVisible() // its owner
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Delete company" })).toHaveCount(0)
  await expect(page.getByText("Clinic scheduling suite")).toHaveCount(0) // her deal stays hers

  await page.goto("/companies")
  await page.getByRole("link", { name: "Zenith Logistics" }).click() // Arjun's own
  await expect(page.getByRole("heading", { name: "Zenith Logistics" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible()
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
