import { USERS, expect, signInAs, test, unique } from "./fixtures.ts"

test.beforeEach(async ({ page }) => {
  await signInAs(page, USERS.admin)
})

test("search contacts, and the search stays in the address", async ({ page }) => {
  await page.goto("/contacts")
  await expect(page.getByRole("link", { name: "Rohan Gupta" })).toBeVisible()
  await page.getByLabel("Search contacts").fill("Priya")
  await expect(page.getByRole("link", { name: "Priya Shah" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Rohan Gupta" })).toHaveCount(0)
  await expect(page).toHaveURL(/q=Priya/)

  await page.reload()
  await expect(page.getByLabel("Search contacts")).toHaveValue("Priya")
  await expect(page.getByRole("link", { name: "Rohan Gupta" })).toHaveCount(0)
})

test("add a contact and log a task for them", async ({ page }) => {
  const last = unique("Verma")
  await page.goto("/contacts")
  await page.getByRole("button", { name: "New contact" }).click()
  await page.getByLabel("First name").fill("Kavya")
  await page.getByLabel("Last name").fill(last)
  await page.getByLabel("Job title").fill("Head of IT")
  await page.getByRole("button", { name: "Add contact" }).click()
  // a new contact opens straight away
  await expect(page.getByRole("heading", { name: `Kavya ${last}` })).toBeVisible()

  const subject = unique("Send the security questionnaire")
  await page.getByRole("tab", { name: "Task" }).click()
  await page.getByLabel("Subject").fill(subject)
  await page.getByRole("button", { name: "Add task" }).click()
  await expect(page.getByText(subject)).toBeVisible()

  // it shows up in My activities, where it can be ticked off
  await page.getByRole("link", { name: "My activities" }).click()
  // once done it leaves "To do" and is listed under "Done & notes"
  await page.getByRole("checkbox", { name: `Mark “${subject}” as done` }).click()
  await expect(page.getByText(subject)).toHaveCount(0)
  await page.getByRole("tab", { name: "Done & notes" }).click()
  await expect(page.getByRole("checkbox", { name: `Mark “${subject}” as not done` })).toBeChecked()
})

test("a deleted contact can be restored, and its history shows who did what", async ({ page }) => {
  const last = unique("Iyer")
  const made = await page.request.post("/api/v1/contacts", {
    headers: { "X-Dealflow-CSRF": "1" },
    data: { first_name: "Nisha", last_name: last, email: "nisha@example.com" },
  })
  const { id } = (await made.json()) as { id: number }
  await page.request.patch(`/api/v1/contacts/${id}`, {
    headers: { "X-Dealflow-CSRF": "1" },
    data: { email: "nisha.iyer@example.com" },
  })

  await page.goto(`/contacts/${id}`)
  await page.getByRole("button", { name: "Delete contact" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Delete contact" }).click()
  await expect(page).toHaveURL(/\/contacts$/)

  await page.getByRole("link", { name: "Recently deleted" }).click()
  await page.getByRole("button", { name: `Restore Nisha ${last}` }).click()
  // restoring opens it again
  await expect(page.getByRole("heading", { name: `Nisha ${last}` })).toBeVisible()
  const history = page.getByRole("heading", { name: "History" }).locator("..")
  await expect(history.getByText("restored this contact")).toBeVisible()
  await expect(history.getByText("deleted this contact")).toBeVisible()
  await expect(
    history.getByText("changed email from “nisha@example.com” to “nisha.iyer@example.com”"),
  ).toBeVisible()
})
