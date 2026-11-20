import { defineConfig, devices } from "@playwright/test"

// End-to-end tests: the real API on a fresh copy of the demo data, with the real front end.
// Run with `npm run e2e` (needs Postgres running; see the README). Ports are separate from the
// dev servers', so they can run side by side.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8010)
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5174)
const CI = Boolean(process.env.CI)

export default defineConfig({
  testDir: "./e2e",
  // the tests share one database, so they run one at a time
  workers: 1,
  fullyParallel: false,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 7_000 },
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // resets the e2e database, then serves the API
      command: "env -u UV_NATIVE_TLS uv run bash scripts/e2e_server.sh",
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/health`,
      env: { E2E_API_PORT: String(API_PORT) },
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { API_URL: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
