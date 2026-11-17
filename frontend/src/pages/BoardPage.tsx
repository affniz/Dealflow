import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  MouseSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Flame, Plus } from "lucide-react"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"

import {
  boardPipelineBoardOptions,
  dealsUpdateDealMutation,
  pipelinesListPipelinesOptions,
} from "@/client/@tanstack/react-query.gen"
import type { Board, BoardColumn, DealPublic } from "@/client/types.gen"
import { DealCard } from "@/components/deals/DealCard"
import { NewDealDialog } from "@/components/deals/NewDealDialog"
import { PageHeader } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Badge, Spinner } from "@/components/ui/card"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { moveDealOnBoard } from "@/lib/board"
import { useToast } from "@/lib/toast"
import { cn, formatMoney, formatMoneyShort } from "@/lib/utils"

export function BoardPage() {
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const mine = params.get("mine") === "1"
  const stalled = params.get("stalled") === "1"
  const [newDealOpen, setNewDealOpen] = useState(false)
  const [dragging, setDragging] = useState<DealPublic | null>(null)

  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const pipelineId = Number(params.get("pipeline")) || pipelines.data?.[0]?.id
  const pipeline = pipelines.data?.find((p) => p.id === pipelineId)
  const boardOptions = boardPipelineBoardOptions({
    path: { pipeline_id: pipelineId ?? 0 },
    query: { owner_id: mine ? user?.id : undefined, rotting: stalled ? true : undefined },
  })
  const board = useQuery({ ...boardOptions, enabled: pipelineId !== undefined })

  const move = useMutation({
    ...dealsUpdateDealMutation(),
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: boardOptions.queryKey })
      const previous = queryClient.getQueryData<Board>(boardOptions.queryKey)
      if (previous) {
        queryClient.setQueryData(
          boardOptions.queryKey,
          moveDealOnBoard(previous, vars.path.deal_id, vars.body.stage_id!),
        )
      }
      return { previous }
    },
    onError: (error, _vars, context) => {
      const previous = (context as { previous?: Board } | undefined)?.previous
      if (previous) queryClient.setQueryData(boardOptions.queryKey, previous)
      toast(apiErrorMessage(error, "Couldn't move the deal"), "error")
    },
    onSettled: () => invalidate(queryClient, ...DEAL_QUERIES),
  })

  // Mouse drags start after 6px so clicks still open the deal; touch needs a short press so
  // swiping still scrolls the board.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
  )

  function onDragStart(e: DragStartEvent) {
    setDragging((e.active.data.current?.deal as DealPublic | undefined) ?? null)
  }

  function onDragEnd(e: DragEndEvent) {
    setDragging(null)
    const deal = e.active.data.current?.deal as DealPublic | undefined
    const toStage = e.over?.data.current?.stageId as number | undefined
    if (!deal || toStage === undefined || toStage === deal.stage_id) return
    move.mutate({ path: { deal_id: deal.id }, body: { stage_id: toStage } })
  }

  function setFlag(key: string, on: boolean) {
    const next = new URLSearchParams(params)
    if (on) next.set(key, "1")
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Pipeline">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {board.data && (
            <span className="mr-2 text-ink-soft">
              {formatMoney(board.data.total_value)} open ·{" "}
              <span className="font-medium text-ink">{formatMoney(board.data.weighted_value)}</span>{" "}
              forecast
            </span>
          )}
          {pipelines.data && pipelines.data.length > 1 && (
            <select
              className="h-9 rounded-md border border-line bg-surface px-2"
              value={pipelineId}
              onChange={(e) => {
                const next = new URLSearchParams(params)
                next.set("pipeline", e.target.value)
                setParams(next, { replace: true })
              }}
              aria-label="Pipeline"
            >
              {pipelines.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          {seesTeam && (
            <Toggle pressed={mine} onChange={(on) => setFlag("mine", on)}>
              My deals
            </Toggle>
          )}
          <Toggle pressed={stalled} onChange={(on) => setFlag("stalled", on)}>
            <Flame /> Stalled only
          </Toggle>
          {canWrite && pipeline && (
            <Button onClick={() => setNewDealOpen(true)}>
              <Plus /> New deal
            </Button>
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
        <DndContext
          sensors={sensors}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDragging(null)}
        >
          <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto px-4 pb-6 md:px-6">
            {board.data.columns.map((col) => (
              <Column key={col.stage.id} column={col} canDrag={canWrite} />
            ))}
          </div>
          <DragOverlay dropAnimation={null}>
            {dragging && <DealCard deal={dragging} lifted />}
          </DragOverlay>
        </DndContext>
      )}

      {pipeline && (
        <NewDealDialog
          open={newDealOpen}
          onClose={() => setNewDealOpen(false)}
          stages={pipeline.stages}
        />
      )}
    </div>
  )
}

function Toggle({
  pressed,
  onChange,
  children,
}: {
  pressed: boolean
  onChange: (pressed: boolean) => void
  children: React.ReactNode
}) {
  return (
    <Button
      variant="outline"
      aria-pressed={pressed}
      onClick={() => onChange(!pressed)}
      className={cn(pressed && "border-brand-600 bg-brand-50 text-brand-700 hover:bg-brand-50")}
    >
      {children}
    </Button>
  )
}

function Column({ column, canDrag }: { column: BoardColumn; canDrag: boolean }) {
  const { setNodeRef, isOver } = useDroppable({
    id: `stage-${column.stage.id}`,
    data: { stageId: column.stage.id },
  })
  return (
    <section
      ref={setNodeRef}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg bg-muted/70 transition-colors",
        isOver && "bg-brand-50 ring-2 ring-brand-600/40",
      )}
      aria-label={column.stage.name}
    >
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
      <div className="flex min-h-16 flex-col gap-2 overflow-y-auto px-2 pb-2">
        {column.deals.map((deal) => (
          <DraggableDeal key={deal.id} deal={deal} disabled={!canDrag} />
        ))}
        {column.deal_count === 0 && (
          <p className="px-2 py-6 text-center text-xs text-ink-faint">No deals</p>
        )}
        {column.deal_count > column.deals.length && (
          <p className="px-2 py-1 text-center text-xs text-ink-faint">
            +{column.deal_count - column.deals.length} more
          </p>
        )}
      </div>
    </section>
  )
}

function DraggableDeal({ deal, disabled }: { deal: DealPublic; disabled: boolean }) {
  // Only pointer listeners are attached: the card's title link is the keyboard/screen-reader
  // entry point, and the deal page's stage bar is the accessible way to change stage.
  const { setNodeRef, listeners, isDragging } = useDraggable({
    id: `deal-${deal.id}`,
    data: { deal },
    disabled,
  })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      className={cn(!disabled && "cursor-grab touch-manipulation", isDragging && "opacity-40")}
    >
      <DealCard deal={deal} />
    </div>
  )
}
