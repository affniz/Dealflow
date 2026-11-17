import { defineConfig } from "@hey-api/openapi-ts"

// Regenerate after backend API changes:
//   (cd ../backend && uv run python scripts/export_openapi.py) && npm run generate-client
export default defineConfig({
  input: "./openapi.json",
  output: { path: "./src/client", format: "prettier" },
  plugins: ["@hey-api/client-fetch", "@hey-api/sdk", "@hey-api/typescript", "@tanstack/react-query"],
})
