import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { formatDateTime } from "@/lib/time"
import { timeAgo } from "@/lib/utils"

/** The "Details" card on a record page: label/value rows, then any custom fields. */
export function DetailsCard({
  rows,
  customFields,
  createdAt,
  updatedAt,
}: {
  rows: [label: string, value: ReactNode][]
  customFields?: Record<string, unknown>
  createdAt: string
  updatedAt: string
}) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold">Details</h2>
      <dl className="space-y-3 text-sm">
        {rows.map(([label, value]) => (
          <Detail key={label} label={label}>
            {value ?? <span className="text-ink-faint">—</span>}
          </Detail>
        ))}
        {Object.entries(customFields ?? {}).map(([k, v]) => (
          <Detail key={`custom-${k}`} label={k.replaceAll("_", " ")}>
            {String(v)}
          </Detail>
        ))}
        <Detail label="Added">
          <time dateTime={createdAt} title={formatDateTime(createdAt)}>
            {timeAgo(createdAt)}
          </time>
        </Detail>
        <Detail label="Updated">
          <time dateTime={updatedAt} title={formatDateTime(updatedAt)}>
            {timeAgo(updatedAt)}
          </time>
        </Detail>
      </dl>
    </Card>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-ink-soft capitalize">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium">{children}</dd>
    </div>
  )
}

/** Shown when a record id doesn't exist or belongs to someone the reader can't see. */
export function NotFound({ what, back }: { what: string; back: ReactNode }) {
  return (
    <div className="p-6 text-sm">
      <p className="text-ink-soft">This {what} doesn't exist or you don't have access to it.</p>
      <div className="mt-2">{back}</div>
    </div>
  )
}
