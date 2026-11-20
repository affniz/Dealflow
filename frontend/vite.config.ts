import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    // the browser calls /api/...; Vite forwards it to FastAPI, so no CORS setup is needed in dev
    // (set API_URL to point it at a backend on another port). /mcp is where Claude connects.
    proxy: {
      "/api": process.env.API_URL ?? "http://localhost:8000",
      "/mcp": process.env.API_URL ?? "http://localhost:8000",
    },
  },
})
