import { clientErrorsReportClientError } from "@/client/sdk.gen"

/**
 * After a deploy, the page a visitor already has open still asks for the old build's
 * JavaScript files, which no longer exist. Browsers word that failure differently.
 */
export function isStaleBuildError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "")
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i.test(
    message,
  )
}

const RELOADED_AT = "dealflow.reloadedForUpdate"

/**
 * Reload once to pick up the new build, at `href` (default: this page). Returns false (and
 * doesn't reload) if this tab already did so moments ago, so a file that's really missing
 * can't cause a reload loop.
 */
export function reloadForUpdate(href?: string) {
  try {
    const last = Number(window.sessionStorage.getItem(RELOADED_AT) ?? 0)
    if (Date.now() - last < 10_000) return false
    window.sessionStorage.setItem(RELOADED_AT, String(Date.now()))
  } catch {
    // no storage: still reload; the error page's button is the fallback next time
  }
  if (href) window.location.assign(href)
  else window.location.reload()
  return true
}

// A dropped connection or a request the browser cancelled isn't a bug in the app
const NOT_A_BUG = /Failed to fetch|NetworkError|Load failed|AbortError|aborted/i
const reported = new Set<string>()

/**
 * Tell the server about a crash in this browser, so it's in the logs (and in Sentry, when that's
 * set up) and not only in this console. At most five different errors per page load; the URL's
 * query and # are left out (a password reset link keeps its secret after the #).
 */
export function reportError(error: unknown, componentStack?: string | null) {
  if (isStaleBuildError(error)) return // handled: the page reloads or says so
  if (error && typeof error === "object" && "status" in error && "statusText" in error) return // a route's 404
  const message =
    error instanceof Error ? `${error.name}: ${error.message}` : String(error ?? "Unknown error")
  if (NOT_A_BUG.test(message) || reported.has(message) || reported.size >= 5) return
  reported.add(message)
  void clientErrorsReportClientError({
    body: {
      message: message.slice(0, 1000),
      stack: error instanceof Error ? error.stack?.slice(0, 8000) : null,
      component_stack: componentStack?.slice(0, 8000) ?? null,
      path: window.location.pathname.slice(0, 500),
    },
  }).catch(() => {
    // reporting is best effort
  })
}
