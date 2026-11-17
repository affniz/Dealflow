import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    // the browser calls /api/...; Vite forwards it to FastAPI, so no CORS setup is needed in dev
    proxy: { "/api": "http://localhost:8000" },
  },
})
