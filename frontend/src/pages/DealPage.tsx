import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, CircleCheck, CircleX, Flame, Pencil, RotateCcw, Trash2 } from "lucide-react"
import { type FormEvent, type ReactNode, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"

import {
  copilotListProposalsOptions,
  dealsDealTimelineOptions,
  dealsDeleteDealMutation,
  dealsMarkLostMutation,
  dealsMarkWonMutation,
  dealsReadDealOptions,
  dealsReopenMutation,
  dealsUpdateDealMutation,
  pipelinesListLostReasonsOptions,
  pipelinesListPipelinesOptions,
} from "@/client/@tanstack/react-query.gen"
import type { DealPublic, DealUpdate } from "@/client/types.gen"
import { ProposalCard } from "@/components/copilot/ProposalCard"
import { ActivityComposer } from "@/components/activities/ActivityComposer"
import { DealForm } from "@/components/deals/DealForm"
import { StageBar } from "@/components/deals/StageBar"
import { Timeline } from "@/components/deals/Timeline"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { Dialog, DialogFooter } from "@/components/ui/dialog"
import { Field, Select, Textarea } from "@/components/ui/field"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { same, toFieldRows } from "@/lib/forms"
import { permissions, useAuth } from "@/lib/auth"
import { useNow } from "@/lib/time"
import { useToast } from "@/lib/toast"
import { formatMoney, timeAgo } from "@/lib/utils"

type DialogName = "edit" | "lost" | "delete" | null

export function DealPage() {
  const dealId = Number(useParams().dealId)
  const { user } = useAuth()
  const { canWrite, isAdmin } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [dialog, setDialog] = useState<DialogName>(null)
  const now = useNow()

  const deal = useQuery(dealsReadDealOptions({ path: { deal_id: dealId } }))
  const timeline = useQuery(dealsDealTimelineOptions({ path: { deal_id: dealId } }))
  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const pending = useQuery(
    copilotListProposalsOptions({ query: { deal_id: dealId, status: "pending" } }),
  )

  const onChanged = () => invalidate(queryClient, ...DEAL_QUERIES)
  const onError = (e: unknown) => toast(apiErrorMessage(e), "error")
  const update = useMutation({ ...dealsUpdateDealMutation(), onSuccess: onChanged, onError })
  const won = useMutation({
    ...dealsMarkWonMutation(),
    onSuccess: () => {
      onChanged()
      toast("Marked as won")
    },
    onError,
  })
  const reopen = useMutation({ ...dealsReopenMutation(), onSuccess: onChanged, onError })

  if (deal.isPending) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner />
      </div>
    )
  }
  if (deal.isError) {
    return (
      <div className="p-6 text-sm">
        <p className="text-ink-soft">This deal doesn't exist or you don't have access to it.</p>
        <Link to="/" className="mt-2 inline-block text-brand-700 hover:underline">
          Back to the pipeline
        </Link>
      </div>
    )
  }

  const d = deal.data
  const pipeline = pipelines.data?.find((p) => p.id === d.pipeline_id)
  const stages = pipeline?.stages ?? []
  const stageName = (id: unknown) => stages.find((s) => s.id === id)?.name ?? "a removed stage"
  const isOpen = d.status === "open"
  const daysInStage = Math.floor((now - new Date(d.stage_changed_at).getTime()) / 86_400_000)

  return (
    <div className="mx-auto max-w-6xl px-4 py-5 md:px-6">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-ink-soft hover:text-ink">
        <ArrowLeft className="size-4" /> Pipeline
      </Link>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{d.title}</h1>
            {d.status === "won" && <Badge tone="success">Won</Badge>}
            {d.status === "lost" && <Badge tone="danger">Lost</Badge>}
            {d.is_rotting && (
              <Badge tone="danger">
                <Flame className="size-3" /> Stalled · {daysInStage} days in {stageName(d.stage_id)}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-ink-soft">
            {[d.company?.name, d.contact?.name].filter(Boolean).join(" · ") ||
              "No company or contact"}
          </p>
          <p className="mt-2 text-2xl font-semibold">{formatMoney(d.value, d.currency ?? "INR")}</p>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            {isOpen ? (
              <>
                <Button
                  className="bg-emerald-600 hover:bg-emerald-700"
                  disabled={won.isPending}
                  onClick={() => won.mutate({ path: { deal_id: d.id } })}
                >
                  <CircleCheck /> Won
                </Button>
                <Button variant="destructive" onClick={() => setDialog("lost")}>
                  <CircleX /> Lost
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                disabled={reopen.isPending}
                onClick={() => reopen.mutate({ path: { deal_id: d.id } })}
              >
                <RotateCcw /> Reopen
              </Button>
            )}
            <Button variant="outline" onClick={() => setDialog("edit")}>
              <Pencil /> Edit
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete deal"
              title="Delete deal"
              onClick={() => setDialog("delete")}
            >
              <Trash2 />
            </Button>
          </div>
        )}
      </div>

      {stages.length > 0 && (
        <div className="mt-5">
          <StageBar
            stages={stages}
            currentId={d.stage_id}
            disabled={!canWrite || !isOpen || update.isPending}
            onSelect={(stage_id) => update.mutate({ path: { deal_id: d.id }, body: { stage_id } })}
          />
          {!isOpen && canWrite && (
            <p className="mt-2 text-xs text-ink-faint">
              Reopen the deal to move it between stages.
            </p>
          )}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <section className="space-y-4 lg:col-span-2" aria-label="Activity">
          {pending.data && pending.data.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold">Waiting for your approval</h2>
              {pending.data.map((p) => (
                <ProposalCard key={p.id} proposal={p} canDecide={canWrite} />
              ))}
            </div>
          )}
          {canWrite && (
            <ActivityComposer
              links={{ deal_id: d.id, contact_id: d.contact_id, company_id: d.company_id }}
            />
          )}
          <h2 className="text-sm font-semibold">Timeline</h2>
          {timeline.isPending ? (
            <Spinner />
          ) : timeline.isError ? (
            <p className="text-sm text-red-600">Couldn't load the timeline.</p>
          ) : (
            <Timeline items={timeline.data} stageName={stageName} canWrite={canWrite} />
          )}
        </section>

        <Card className="h-fit p-4">
          <h2 className="mb-3 text-sm font-semibold">Details</h2>
          <dl className="space-y-3 text-sm">
            <Detail label="Owner">{d.owner?.name ?? "—"}</Detail>
            <Detail label="Company">{d.company?.name ?? "—"}</Detail>
            <Detail label="Contact">{d.contact?.name ?? "—"}</Detail>
            <Detail label="Pipeline">{pipeline?.name ?? "—"}</Detail>
            <Detail label="Expected close">
              {d.expected_close_date
                ? new Date(`${d.expected_close_date}T00:00:00`).toLocaleDateString(undefined, {
                    dateStyle: "medium",
                  })
                : "—"}
            </Detail>
            <Detail label="In this stage since">{timeAgo(d.stage_changed_at)}</Detail>
            <Detail label="Created">{timeAgo(d.created_at)}</Detail>
            {d.closed_at && <Detail label="Closed">{timeAgo(d.closed_at)}</Detail>}
            {Object.entries(d.custom_fields ?? {}).map(([k, v]) => (
              <Detail key={k} label={k}>
                {String(v)}
              </Detail>
            ))}
          </dl>
        </Card>
      </div>

      <EditDealDialog
        deal={d}
        open={dialog === "edit"}
        onClose={() => setDialog(null)}
        canAssign={isAdmin}
      />
      <LostDialog deal={d} open={dialog === "lost"} onClose={() => setDialog(null)} />
      <DeleteDialog deal={d} open={dialog === "delete"} onClose={() => setDialog(null)} />
    </div>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}

function EditDealDialog({
  deal,
  open,
  onClose,
  canAssign,
}: {
  deal: DealPublic
  open: boolean
  onClose: () => void
  canAssign: boolean
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const update = useMutation({
    ...dealsUpdateDealMutation(),
    onSuccess: () => {
      invalidate(queryClient, ...DEAL_QUERIES)
      onClose()
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  return (
    <Dialog open={open} onClose={onClose} title="Edit deal">
      <DealForm
        key={String(open)}
        linked={{ company: deal.company, contact: deal.contact }}
        initial={{
          title: deal.title,
          value: String(deal.value ?? ""),
          stage_id: null,
          company_id: deal.company_id ?? null,
          contact_id: deal.contact_id ?? null,
          owner_id: deal.owner_id,
          expected_close_date: deal.expected_close_date ?? null,
          fields: toFieldRows(deal.custom_fields),
        }}
        canAssign={canAssign}
        busy={update.isPending}
        error={error}
        submitLabel="Save"
        onCancel={onClose}
        onSubmit={(v, customFields) => {
          setError(null)
          // PATCH only what changed, so untouched links aren't re-validated
          const next: DealUpdate = {
            title: v.title.trim(),
            value: v.value || "0",
            company_id: v.company_id,
            contact_id: v.contact_id,
            expected_close_date: v.expected_close_date,
            ...(canAssign && v.owner_id ? { owner_id: v.owner_id } : {}),
          }
          const current: Record<string, unknown> = {
            ...deal,
            value: String(deal.value ?? ""),
            company_id: deal.company_id ?? null,
            contact_id: deal.contact_id ?? null,
            expected_close_date: deal.expected_close_date ?? null,
          }
          const body = Object.fromEntries(
            Object.entries(next).filter(([k, val]) =>
              k === "value" ? Number(val) !== Number(current.value) : val !== current[k],
            ),
          ) as DealUpdate
          if (!same(customFields, deal.custom_fields ?? {})) body.custom_fields = customFields
          if (Object.keys(body).length === 0) return onClose()
          update.mutate({ path: { deal_id: deal.id }, body })
        }}
      />
    </Dialog>
  )
}

function LostDialog({
  deal,
  open,
  onClose,
}: {
  deal: DealPublic
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const reasons = useQuery({ ...pipelinesListLostReasonsOptions(), enabled: open })
  const [reasonId, setReasonId] = useState("")
  const [note, setNote] = useState("")
  const [error, setError] = useState<string | null>(null)
  const lost = useMutation({
    ...dealsMarkLostMutation(),
    onSuccess: () => {
      invalidate(queryClient, ...DEAL_QUERIES)
      toast("Marked as lost")
      setReasonId("")
      setNote("")
      onClose()
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    lost.mutate({
      path: { deal_id: deal.id },
      body: { lost_reason_id: Number(reasonId), note: note.trim() || null },
    })
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Mark as lost"
      description="The reason feeds the lost-deal report."
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Reason" htmlFor="lost-reason">
          <Select
            id="lost-reason"
            required
            value={reasonId}
            onChange={(e) => setReasonId(e.target.value)}
          >
            <option value="" disabled>
              Choose a reason
            </option>
            {reasons.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Note (optional)" htmlFor="lost-note">
          <Textarea
            id="lost-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={2000}
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
          <Button type="submit" variant="destructive" disabled={lost.isPending}>
            Mark as lost
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  )
}

function DeleteDialog({
  deal,
  open,
  onClose,
}: {
  deal: DealPublic
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const remove = useMutation({
    ...dealsDeleteDealMutation(),
    onSuccess: () => {
      invalidate(queryClient, ...DEAL_QUERIES)
      toast(`Deleted “${deal.title}”`)
      navigate("/", { replace: true })
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Delete this deal?"
      description="Its history is deleted too. Activities stay on the contact and company. This can't be undone."
    >
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="destructive"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ path: { deal_id: deal.id } })}
        >
          Delete deal
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
