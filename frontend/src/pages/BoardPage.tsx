import { useQuery } from "@tanstack/react-query"
import { Flame } from "lucide-react"
import { useState } from "react"

import {
  boardPipelineBoardOptions,
  pipelinesListPipelinesOptions,
} from "@/client/@tanstack/react-query.gen"
import type { BoardColumn, DealPublic } from "@/client/types.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { cn, formatMoney, formatMoneyShort, initials } from "@/lib/utils"

/** Read-only board for 3a; drag-and-drop and the deal page arrive in 3b. */
export function BoardPage() {
  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const [selected, setSelected] = useState<number | null>(null)
  const pipelineId = selected ?? pipelines.data?.[0]?.id
  const board = useQuery({
    ...boardPipelineBoardOptions({ path: { pipeline_id: pipelineId ?? 0 } }),
    enabled: pipelineId !== undefined,
  })

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Pipeline">
        <div className="flex items-center gap-3 text-sm">
          {board.data && (
            <span className="text-ink-soft">
              {formatMoney(board.data.total_value)} open ·{" "}
              <span className="font-medium text-ink">{formatMoney(board.data.weighted_value)}</span>{" "}
              forecast
            </span>
          )}
          {pipelines.data && pipelines.data.length > 1 && (
            <select
              className="h-9 rounded-md border border-line bg-surface px-2"
              value={pipelineId}
              onChange={(e) => setSelected(Number(e.target.value))}
              aria-label="Pipeline"
            >
              {pipelines.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </PageHeader>

      {board.isPending || pipelines.isPending ? (
        <div className="grid flex-1 place-items-center">
          <Spinner />
        </div>
      ) : board.isError ? (
        <p className="px-6 text-sm text-red-600">Couldn't load the board.</p>
      ) : (
        <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto px-4 pb-6 md:px-6">
          {board.data.columns.map((col) => (
            <Column key={col.stage.id} column={col} />
          ))}
        </div>
      )}
    </div>
  )
}

function Column({ column }: { column: BoardColumn }) {
  return (
    <section className="flex w-72 shrink-0 flex-col rounded-lg bg-muted/70" aria-label={column.stage.name}>
      <header className="space-y-1 p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">{column.stage.name}</h2>
          <span className="text-xs text-ink-faint">{column.stage.probability}%</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-soft">
          <span>
            {column.deal_count} {column.deal_count === 1 ? "deal" : "deals"}
          </span>
          <span>·</span>
          <span>{formatMoneyShort(column.total_value)}</span>
          <span>·</span>
          <span title="Value × win probability">
            {formatMoneyShort(column.weighted_value)} weighted
          </span>
        </div>
        {column.rotting_count > 0 && (
          <Badge tone="danger">
            <Flame className="size-3" /> {column.rotting_count} stalled
          </Badge>
        )}
      </header>
      <div className="flex flex-col gap-2 overflow-y-auto px-2 pb-2">
        {column.deals.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
        {column.deal_count === 0 && (
          <p className="px-2 py-6 text-center text-xs text-ink-faint">No deals</p>
        )}
      </div>
    </section>
  )
}

function DealCard({ deal }: { deal: DealPublic }) {
  return (
    <Card className={cn("p-3", deal.is_rotting && "border-red-300 dark:border-red-800")}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium leading-snug">{deal.title}</h3>
        {deal.is_rotting && (
          <Flame className="size-4 shrink-0 text-red-500" aria-label="Stalled deal" />
        )}
      </div>
      {(deal.company || deal.contact) && (
        <p className="mt-1 truncate text-xs text-ink-soft">
          {[deal.company?.name, deal.contact?.name].filter(Boolean).join(" · ")}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between">
        <span className="text-sm font-semibold">{formatMoney(deal.value, deal.currency ?? "INR")}</span>
        {deal.owner && (
          <span
            className="grid size-6 place-items-center rounded-full bg-surface text-[10px] font-semibold ring-1 ring-line"
            title={deal.owner.name}
          >
            {initials(deal.owner.name)}
          </span>
        )}
      </div>
    </Card>
  )
}
