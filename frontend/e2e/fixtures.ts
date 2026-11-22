import { type Page, expect, test } from "@playwright/test"

// Demo data (backend/app/demo_data.py), loaded fresh for every run
export const PASSWORD = "demo-password"
export const USERS = {
  admin: "meera@dealflow.dev",
  agent: "arjun@dealflow.dev",
  otherAgent: "sana@dealflow.dev",
  viewer: "vikram@dealflow.dev",
} as const

/** Sign in through the API, skipping the sign-in form: the session cookie it sets is shared
 * with the page. */
export async function signInAs(page: Page, email: string) {
  const res = await page.request.post("/api/v1/login/access-token", {
    form: { username: email, password: PASSWORD },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
}

/** A name no other test (or earlier run) has used. */
export function unique(name: string) {
  return `${name} ${Date.now().toString(36)}`
}

export { expect, test }
