import { useSearchParams } from "react-router-dom"

/**
 * List state kept in the URL (search, filters, page), so a list survives a reload, the back
 * button and a shared link. Changing any filter goes back to the first page.
 */
export function useListParams() {
  const [params, setParams] = useSearchParams()
  function set(changes: Record<string, string | number | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key)
      else next.set(key, String(value))
    }
    if (!("page" in changes)) next.delete("page")
    setParams(next, { replace: true })
  }
  const page = Math.max(1, Number(params.get("page")) || 1)
  return { params, set, page }
}
