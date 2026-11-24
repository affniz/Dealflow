import { defineConfig, mergeConfig } from "vitest/config"

import viteConfig from "./vite.config.ts"

// Unit and component tests (npm test): the app's own Vite setup, in a simulated browser (jsdom).
// The end-to-end tests in e2e/ run separately with Playwright.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      include: ["src/**/*.test.{ts,tsx}"],
      setupFiles: ["./src/test/setup.ts"],
      restoreMocks: true,
      unstubGlobals: true,
    },
  }),
)
