import { ChevronLeft, ChevronRight, Search, X } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/** A search field that waits for a pause in typing before searching. */
export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  label: string
}) {
  const [text, setText] = useState(value)
  const [synced, setSynced] = useState(value)
  const [sent, setSent] = useState(value)
  // follow outside changes (the back button, a cleared filter), but not the echo of our own
  // search arriving while the person keeps typing
  if (value !== synced) {
    setSynced(value)
    if (value !== sent) setText(value)
  }

  function send(next: string) {
    setSent(next)
    onChange(next)
  }

  useEffect(() => {
    const next = text.trim()
    if (next === value) return
    const timer = setTimeout(() => {
      setSent(next)
      onChange(next)
    }, 250)
    return () => clearTimeout(timer)
  }, [text, value, onChange])

  return (
    <div className="relative w-full sm:w-72">
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" />
      <Input
        type="search"
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="pr-8 pl-9 [&::-webkit-search-cancel-button]:hidden"
      />
      {text && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => {
            setText("")
            send("")
          }}
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-ink-faint hover:text-ink"
        >
          <X className="size-4" />
        </button>
      )}
    </div>
  )
}

/** "1–50 of 132" with previous and next buttons; hidden when everything fits on one page. */
export function Pager({
  page,
  pageSize,
  count,
  onPage,
}: {
  page: number
  pageSize: number
  count: number
  onPage: (page: number) => void
}) {
  if (count <= pageSize && page === 1) return null
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, count)
  return (
    <div className="flex items-center justify-end gap-2 py-3 text-sm text-ink-soft">
      <span>
        {count === 0 ? "0" : `${first}–${last}`} of {count}
      </span>
      <Button
        variant="outline"
        size="icon"
        aria-label="Previous page"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        <ChevronLeft />
      </Button>
      <Button
        variant="outline"
        size="icon"
        aria-label="Next page"
        disabled={last >= count}
        onClick={() => onPage(page + 1)}
      >
        <ChevronRight />
      </Button>
    </div>
  )
}

/** The message shown when a list is empty, with what to do next. */
export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-soft">{children}</div>}
    </div>
  )
}
