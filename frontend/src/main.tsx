import "./index.css"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"

import { AuthProvider } from "@/components/AuthProvider"
import { ToastProvider } from "@/components/ToastProvider"
import { router } from "@/router"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Errors the API answered on purpose (not found, forbidden, invalid) carry a "detail" and
      // won't change on retry; only retry network failures.
      retry: (failureCount, error) =>
        !(error && typeof error === "object" && "detail" in error) && failureCount < 2,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
