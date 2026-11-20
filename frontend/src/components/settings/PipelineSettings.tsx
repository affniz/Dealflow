import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  pipelinesAddStageMutation,
  pipelinesCreatePipelineMutation,
  pipelinesDeleteStageMutation,
  pipelinesListPipelinesOptions,
  pipelinesReorderStagesMutation,
  pipelinesUpdatePipelineMutation,
  pipelinesUpdateStageMutation,
} from "@/client/@tanstack/react-query.gen"
import type { PipelinePublic, StagePublic } from "@/client/types.gen"
import { InlineInput } from "@/components/settings/InlineInput"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm"
import { Dialog, DialogFooter } from "@/components/ui/dialog"
import { Field } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { apiErrorMessage, invalidate } from "@/lib/api"
import { useToast } from "@/lib/toast"

// everything that shows stages, stage names or forecasts
const QUERIES = [
  "pipelinesListPipelines",
  "pipelinesReadPipeline",
  "boardPipelineBoard",
  "dashboardPipelineSummary",
]

const DEFAULT_STAGES = [
  { name: "Lead", probability: 10 },
  { name: "Qualified", probability: 25 },
  { name: "Proposal", probability: 50 },
  { name: "Negotiation", probability: 75 },
]

/** Pipelines, their stages (order, names, win chance) and when deals count as stalled. */
export function PipelineSettings() {
  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const [adding, setAdding] = useState(false)
  return (
    <section aria-labelledby="pipelines" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="pipelines" className="text-base font-semibold">
            Pipelines and stages
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-soft">
            Stages run left to right on the board. Each stage's win chance weights the forecast; a
            deal that sits in one stage longer than the pipeline's limit is flagged as stalled.
            Changes save as you go.
          </p>
        </div>
        <Button variant="outline" onClick={() => setAdding(true)}>
          <Plus /> New pipeline
        </Button>
      </div>
      {pipelines.isPending ? (
        <Spinner />
      ) : (
        pipelines.data?.map((p) => <PipelineCard key={p.id} pipeline={p} />)
      )}
      <NewPipelineDialog open={adding} onClose={() => setAdding(false)} />
    </section>
  )
}

/** Refresh everything that shows pipelines after a change, and say what happened. */
function useSaveHandlers<T = unknown>(message?: (data: T) => string) {
  const queryClient = useQueryClient()
  const toast = useToast()
  return {
    onSuccess: (data: T) => {
      invalidate(queryClient, ...QUERIES)
      if (message) toast(message(data))
    },
    onError: (e: unknown) => toast(apiErrorMessage(e), "error"),
  }
}

function PipelineCard({ pipeline: p }: { pipeline: PipelinePublic }) {
  const [removing, setRemoving] = useState<StagePublic | null>(null)
  const [newName, setNewName] = useState("")
  const [newChance, setNewChance] = useState("")
  const saved = useSaveHandlers(() => "Pipeline saved")
  const stageSaved = useSaveHandlers<StagePublic>((s) => `Saved ${s.name}`)
  const stageAdded = useSaveHandlers<StagePublic>((s) => `Added ${s.name}`)
  const quiet = useSaveHandlers()
  const stageDeleted = useSaveHandlers(() => "Stage deleted")
  const updatePipeline = useMutation({ ...pipelinesUpdatePipelineMutation(), ...saved })
  const updateStage = useMutation({ ...pipelinesUpdateStageMutation(), ...stageSaved })
  const queryClient = useQueryClient()
  const reorder = useMutation({
    ...pipelinesReorderStagesMutation(),
    ...quiet,
    onSuccess: (saved: PipelinePublic) => {
      // show the new order straight away; the refetch then confirms it
      queryClient.setQueryData(pipelinesListPipelinesOptions().queryKey, (old) =>
        old?.map((x) => (x.id === saved.id ? saved : x)),
      )
      quiet.onSuccess(saved)
    },
  })
  const addStage = useMutation({ ...pipelinesAddStageMutation(), ...stageAdded })
  const deleteStage = useMutation({ ...pipelinesDeleteStageMutation(), ...stageDeleted })
  const stages = p.stages ?? []

  function move(index: number, by: -1 | 1) {
    const ids = stages.map((s) => s.id)
    ;[ids[index], ids[index + by]] = [ids[index + by]!, ids[index]!]
    reorder.mutate({ path: { pipeline_id: p.id }, body: { stage_ids: ids } })
  }

  function add(e: FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    addStage.mutate(
      {
        path: { pipeline_id: p.id },
        body: { name: newName.trim(), probability: clampChance(newChance) },
      },
      {
        onSuccess: () => {
          setNewName("")
          setNewChance("")
        },
      },
    )
  }

  return (
    <Card>
      <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-[1fr_auto]">
        <Field label="Pipeline name" htmlFor={`pipeline-${p.id}-name`}>
          <InlineInput
            key={p.name}
            id={`pipeline-${p.id}-name`}
            value={p.name}
            maxLength={100}
            onSave={(name) =>
              updatePipeline.mutate({ path: { pipeline_id: p.id }, body: { name } })
            }
          />
        </Field>
        <Field label="Stalled after (days)" htmlFor={`pipeline-${p.id}-rot`}>
          <InlineInput
            key={p.rotting_days}
            id={`pipeline-${p.id}-rot`}
            type="number"
            min={1}
            inputMode="numeric"
            value={String(p.rotting_days ?? 14)}
            onSave={(v) =>
              updatePipeline.mutate({
                path: { pipeline_id: p.id },
                body: { rotting_days: Math.max(1, Math.round(Number(v)) || 14) },
              })
            }
            className="block w-28"
          />
        </Field>
      </div>

      <div className="px-4 pt-3 text-xs font-medium text-ink-soft">
        <div className="grid grid-cols-[1fr_6.5rem_5.5rem] gap-2">
          <span>Stage</span>
          <span>Win chance</span>
          <span className="sr-only">Actions</span>
        </div>
      </div>
      <ol className="space-y-1 px-4 py-2">
        {stages.map((s, i) => (
          <li key={s.id} className="grid grid-cols-[1fr_6.5rem_5.5rem] items-center gap-2">
            <InlineInput
              key={`${s.name}`}
              aria-label={`Name of stage ${i + 1}`}
              value={s.name}
              maxLength={100}
              onSave={(name) => updateStage.mutate({ path: { stage_id: s.id }, body: { name } })}
            />
            <div className="flex items-center gap-1">
              <InlineInput
                key={s.probability}
                aria-label={`Win chance for ${s.name}, percent`}
                type="number"
                min={0}
                max={100}
                inputMode="numeric"
                value={String(s.probability ?? 0)}
                onSave={(v) =>
                  updateStage.mutate({
                    path: { stage_id: s.id },
                    body: { probability: clampChance(v) },
                  })
                }
              />
              <span className="text-sm text-ink-faint">%</span>
            </div>
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={`Move ${s.name} earlier`}
                disabled={i === 0 || reorder.isPending}
                onClick={() => move(i, -1)}
              >
                <ArrowUp />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={`Move ${s.name} later`}
                disabled={i === stages.length - 1 || reorder.isPending}
                onClick={() => move(i, 1)}
              >
                <ArrowDown />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={`Delete ${s.name}`}
                disabled={stages.length <= 1}
                onClick={() => setRemoving(s)}
              >
                <Trash2 />
              </Button>
            </div>
          </li>
        ))}
      </ol>
      <form
        onSubmit={add}
        className="grid grid-cols-[1fr_6.5rem_5.5rem] items-center gap-2 border-t border-line px-4 py-3"
      >
        <Input
          aria-label="New stage name"
          placeholder="Add a stage"
          maxLength={100}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className="h-8"
        />
        <div className="flex items-center gap-1">
          <Input
            aria-label="New stage win chance, percent"
            type="number"
            min={0}
            max={100}
            placeholder="0"
            value={newChance}
            onChange={(e) => setNewChance(e.target.value)}
            className="h-8"
          />
          <span className="text-sm text-ink-faint">%</span>
        </div>
        <Button type="submit" size="sm" disabled={!newName.trim() || addStage.isPending}>
          <Plus /> Add
        </Button>
      </form>
      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        onConfirm={() =>
          removing &&
          deleteStage.mutate(
            { path: { stage_id: removing.id } },
            { onSettled: () => setRemoving(null) },
          )
        }
        busy={deleteStage.isPending}
        title={`Delete the ${removing?.name ?? ""} stage?`}
        description="Only an empty stage can be deleted: move its deals (open or closed) to another stage first."
        confirmLabel="Delete stage"
      />
    </Card>
  )
}

function clampChance(v: string) {
  return Math.min(100, Math.max(0, Math.round(Number(v)) || 0))
}

function NewPipelineDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const create = useMutation({
    ...pipelinesCreatePipelineMutation(),
    onSuccess: (p) => {
      invalidate(queryClient, ...QUERIES)
      toast(`Added the ${p.name} pipeline`)
      setName("")
      onClose()
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New pipeline"
      description="It starts with the usual four stages; rename, reorder or add to them afterwards."
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          create.mutate({
            body: {
              name: name.trim(),
              rotting_days: 14,
              stages: DEFAULT_STAGES.map((s, position) => ({ ...s, position })),
            },
          })
        }}
        className="space-y-4"
      >
        <Field label="Name" htmlFor="new-pipeline-name">
          <Input
            id="new-pipeline-name"
            required
            maxLength={100}
            autoFocus
            placeholder="e.g. Renewals"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            Add pipeline
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  )
}
