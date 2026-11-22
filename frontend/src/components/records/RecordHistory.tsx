import { History, PencilLine, Plus, RotateCcw, Trash2 } from "lucide-react"
import { type ReactNode, useState } from "react"

import type { HistoryItem } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { changeLines } from "@/lib/history"
import { timeAgo } from "@/lib/utils"

const SHOWN = 5

/** Who created, changed, deleted or restored a contact or company. */
export function RecordHistory({
  items,
  isPending,
  noun,
}: {
  items: HistoryItem[] | undefined
  isPending: boolean
  noun: "contact" | "company"
}) {
  const [all, setAll] = useState(false)
  const list = items ?? []
  const shown = all ? list : list.slice(0, SHOWN)
  return (
    <Card className="p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <History className="size-4 text-ink-soft" aria-hidden /> History
      </h2>
      {isPending ? (
        <Spinner />
      ) : list.length === 0 ? (
        <p className="text-sm text-ink-faint">No changes recorded yet.</p>
      ) : (
        <ol className="space-y-3">
          {shown.map((item) => (
            <Entry key={item.id} item={item} noun={noun} />
          ))}
        </ol>
      )}
      {list.length > SHOWN && (
        <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${list.length}`}
        </Button>
      )}
    </Card>
  )
}

function Entry({ item, noun }: { item: HistoryItem; noun: string }) {
  const who = item.actor?.name ?? "Dealflow"
  let icon: ReactNode = <PencilLine />
  let lines: string[] = []
  switch (item.kind) {
    case "created":
      icon = <Plus />
      lines = [`added this ${noun}`]
      break
    case "deleted":
      icon = <Trash2 />
      lines = [`deleted this ${noun}`]
      break
    case "restored":
      icon = <RotateCcw />
      lines = [`restored this ${noun}`]
      break
    default:
      lines = changeLines(item.data.changes)
  }
  return (
    <li className="flex gap-2.5 text-sm">
      <span className="mt-0.5 text-ink-faint [&_svg]:size-3.5" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <p className="break-words">
          <span className="font-medium">{who}</span> {lines[0]}
        </p>
        {lines.slice(1).map((line) => (
          <p key={line} className="break-words text-ink-soft">
            {line}
          </p>
        ))}
        <time dateTime={item.created_at} className="text-xs text-ink-faint">
          {timeAgo(item.created_at)}
        </time>
      </div>
    </li>
  )
}
