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
