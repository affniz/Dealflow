import "./index.css"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"

import { AuthProvider } from "@/components/AuthProvider"
import { ErrorBoundary } from "@/components/ErrorScreens"
import { ToastProvider } from "@/components/ToastProvider"
import { reloadForUpdate } from "@/lib/errors"
import { router } from "@/router"

// A page's JavaScript failed to download, most likely because a deploy replaced the build this
// tab started with: reload once to get the new one (if that doesn't help, the error page says so).
// The address only changes once the page has loaded, so go to the page being opened.
window.addEventListener("vite:preloadError", (event) => {
  const to = router.state.navigation.location
  if (reloadForUpdate(to ? `${to.pathname}${to.search}${to.hash}` : undefined)) {
    event.preventDefault()
  }
})

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
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
