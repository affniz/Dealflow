import { type Page, expect, test } from "@playwright/test"

// Demo data (backend/app/demo_data.py), loaded fresh for every run
export const PASSWORD = "demo-password"
export const USERS = {
  admin: "meera@dealflow.dev",
  agent: "arjun@dealflow.dev",
  otherAgent: "sana@dealflow.dev",
  viewer: "vikram@dealflow.dev",
} as const

/** Sign in through the API and hand the token to the app, skipping the sign-in form. */
export async function signInAs(page: Page, email: string) {
  const res = await page.request.post("/api/v1/login/access-token", {
    form: { username: email, password: PASSWORD },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  const { access_token } = (await res.json()) as { access_token: string }
  await page.addInitScript((token) => {
    window.localStorage.setItem("dealflow.token", token)
  }, access_token)
}

/** A name no other test (or earlier run) has used. */
export function unique(name: string) {
  return `${name} ${Date.now().toString(36)}`
}

export { expect, test }
