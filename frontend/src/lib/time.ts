import { useSyncExternalStore } from "react"

// One shared clock for the whole app: it ticks every 30 seconds, and straight away when the tab
// comes back into view (timers are throttled in background tabs and stop while a laptop sleeps).
const TICK_MS = 30_000
let now = Date.now()
const listeners = new Set<() => void>()
let started = false

function tick() {
  now = Date.now()
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (!started) {
    started = true
    setInterval(tick, TICK_MS)
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") tick()
    })
  }
  return () => {
    listeners.delete(listener)
  }
}

/**
 * The current time, updated every 30 seconds, so "overdue" labels and "today" stay right on a
 * page left open. Renders stay pure: every component reads the same value until the next tick.
 */
export function useNow() {
  return useSyncExternalStore(subscribe, () => now)
}

/** An ISO time as the value of an <input type="datetime-local"> in the browser's time zone. */
export function toLocalInput(iso: string | null | undefined) {
  if (!iso) return ""
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** The value of an <input type="datetime-local"> as an ISO time, or null when empty. */
export function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : null
}

/** Midnight at the start of the day after `now`, in the browser's time zone. */
export function startOfTomorrow(now: number) {
  const d = new Date(now)
  d.setHours(24, 0, 0, 0)
  return d
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
}
