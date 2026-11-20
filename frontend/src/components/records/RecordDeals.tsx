import { useQuery } from "@tanstack/react-query"
import { Flame, Plus } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import {
  dealsListDealsOptions,
  pipelinesListPipelinesOptions,
} from "@/client/@tanstack/react-query.gen"
import type { NamedRef } from "@/client/types.gen"
import { NewDealDialog } from "@/components/deals/NewDealDialog"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { formatMoney } from "@/lib/utils"

const ORDER = { open: 0, won: 1, lost: 2 } as const

/** The deals card on a contact or company page: open deals first, then won and lost. */
export function RecordDeals({
  filter,
  company,
  contact,
  canWrite,
}: {
  filter: { contact_id: number } | { company_id: number }
  company?: NamedRef | null
  contact?: NamedRef | null
  canWrite: boolean
}) {
  const [adding, setAdding] = useState(false)
  const deals = useQuery(dealsListDealsOptions({ query: { ...filter, limit: 100 } }))
  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const stages = new Map(pipelines.data?.flatMap((p) => p.stages.map((s) => [s.id, s.name])))
  const firstPipeline = pipelines.data?.[0]
  const rows = [...(deals.data?.data ?? [])].sort((a, b) => ORDER[a.status] - ORDER[b.status])

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Deals{deals.data && deals.data.count > 0 ? ` · ${deals.data.count}` : ""}
        </h2>
        {canWrite && firstPipeline && (
          <Button variant="ghost" size="sm" onClick={() => setAdding(true)}>
            <Plus /> Add
          </Button>
        )}
      </div>
      {deals.isPending ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink-faint">No deals yet.</p>
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {rows.map((d) => (
            <li key={d.id}>
              <Link
                to={`/deals/${d.id}`}
                className="flex items-start justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{d.title}</p>
                  <p className="flex items-center gap-1.5 text-xs text-ink-soft">
                    {d.status === "open" ? (
                      (stages.get(d.stage_id) ?? "Open")
                    ) : (
                      <Badge
                        tone={d.status === "won" ? "success" : "danger"}
                        className="capitalize"
                      >
                        {d.status}
                      </Badge>
                    )}
                    {d.is_rotting && (
                      <span className="flex items-center gap-0.5 text-red-600">
                        <Flame className="size-3" /> Stalled
                      </span>
                    )}
                  </p>
                </div>
                <span className="shrink-0 text-sm tabular-nums">
                  {formatMoney(d.value, d.currency ?? "INR")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {firstPipeline && (
        <NewDealDialog
          open={adding}
          onClose={() => setAdding(false)}
          stages={firstPipeline.stages}
          company={company}
          contact={contact}
        />
      )}
    </Card>
  )
}
