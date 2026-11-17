import { useState } from "react"

/** The time when the component mounted, so renders stay pure; good enough for "overdue" labels. */
export function useNow() {
  const [now] = useState(() => Date.now())
  return now
}
