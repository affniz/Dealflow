import { useMutation, useQuery } from "@tanstack/react-query"
import { Bot, CircleAlert, Inbox, Play } from "lucide-react"
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"

import {
  copilotCopilotStatusOptions,
  copilotListAgentRunsOptions,
  copilotListProposalsOptions,
  copilotStartPipelineReviewMutation,
} from "@/client/@tanstack/react-query.gen"
import type { AgentRunPublic } from "@/client/types.gen"
import { ProposalCard } from "@/components/copilot/ProposalCard"
import { RichText } from "@/components/copilot/RichText"
import { PageHeader } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { apiErrorMessage } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { useToast } from "@/lib/toast"
import { cn, timeAgo } from "@/lib/utils"

type Tab = "pending" | "decided"

/** Suggestions from the agents waiting for a decision, and the pipeline agent's review notes. */
export function InboxPage() {
  const { user } = useAuth()
  const { canWrite, isAdmin } = permissions(user)
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get("tab") === "decided" ? "decided" : "pending"
  const everyone = isAdmin && params.get("everyone") === "1"
  const [queuedAt, setQueuedAt] = useState<number | null>(null)

  const status = useQuery(copilotCopilotStatusOptions())
  const proposals = useQuery({
    ...copilotListProposalsOptions({
      query: { status: tab === "pending" ? "pending" : undefined, everyone },
    }),
    // a review queued from here finishes in the background: check back while waiting
    refetchInterval: queuedAt ? 10_000 : false,
  })
  const runs = useQuery({
    ...copilotListAgentRunsOptions({ query: { limit: 20 } }),
    refetchInterval: queuedAt ? 10_000 : false,
  })
  const startReview = useMutation({
    ...copilotStartPipelineReviewMutation(),
    onSuccess: () => {
      setQueuedAt(Date.now())
      toast("Review started. Suggestions will appear here in a minute or two.")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })

  const shown = (proposals.data ?? []).filter((p) =>
    tab === "pending" ? p.status === "pending" : p.status !== "pending",
  )

  function set(key: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (value === null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const hour = status.data?.review_hour ?? 7
  const schedule = `every morning at ${String(hour).padStart(2, "0")}:00`

  return (
    <>
      <PageHeader title="Agent inbox">
        {isAdmin && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input
                type="checkbox"
                className="size-4 accent-brand-600"
                checked={everyone}
                onChange={(e) => set("everyone", e.target.checked ? "1" : null)}
              />
              Everyone's suggestions
            </label>
            <Button
              variant="outline"
              disabled={startReview.isPending || status.data?.enabled === false}
              onClick={() => startReview.mutate({})}
              title={
                status.data?.enabled === false ? "Add ANTHROPIC_API_KEY to turn on AI" : undefined
              }
            >
              <Play /> Review stalled deals now
            </Button>
          </div>
        )}
      </PageHeader>

      <div className="grid gap-6 px-4 pb-8 md:px-6 lg:grid-cols-3">
        <section className="lg:col-span-2" aria-label="Suggestions">
          <div role="tablist" className="mb-4 flex gap-1 border-b border-line">
            {(["pending", "decided"] as const).map((t) => (
              <button
                key={t}
                role="tab"
                type="button"
                aria-selected={tab === t}
                onClick={() => set("tab", t === "pending" ? null : t)}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
                  tab === t
                    ? "border-brand-600 text-brand-700"
                    : "border-transparent text-ink-soft hover:text-ink",
                )}
              >
                {t === "pending" ? "Waiting for a decision" : "Decided"}
              </button>
            ))}
          </div>

          {proposals.isPending ? (
            <Spinner />
          ) : shown.length === 0 ? (
            <Card className="p-8 text-center text-sm text-ink-soft">
              <Inbox className="mx-auto mb-2 size-6 text-ink-faint" aria-hidden />
              {tab === "pending" ? (
                <>
                  Nothing waiting. The pipeline agent reviews stalled deals {schedule} and puts its
                  suggestions here; Copilot's suggestions appear here too.
                </>
              ) : (
                "No decided suggestions yet."
              )}
            </Card>
          ) : (
            <div className="space-y-3">
              {shown.map((p) => (
                <ProposalCard
                  key={p.id}
                  proposal={p}
                  canDecide={canWrite && (p.user_id === user?.id || isAdmin)}
                  showDeal
                />
              ))}
            </div>
          )}
        </section>

        <aside aria-label="Pipeline agent reviews" className="space-y-3">
          <div className="flex items-center gap-2">
            <Bot className="size-4 text-brand-600" aria-hidden />
            <h2 className="text-sm font-semibold">Pipeline agent's notes</h2>
          </div>
          <p className="text-xs text-ink-faint">
            It reviews stalled deals {schedule} and leaves a note for each deal's owner.
            {status.data?.enabled === false && " AI isn't set up on this server yet."}
          </p>
          {status.data?.pipeline_budget_reached && (
            <p
              role="status"
              className="flex items-start gap-1.5 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300"
            >
              <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
              Reviews are paused: {status.data.pipeline_budget_reached}
            </p>
          )}
          {runs.isPending ? (
            <Spinner />
          ) : runs.data?.length ? (
            runs.data.map((run) => <RunCard key={run.id} run={run} />)
          ) : (
            <p className="text-sm text-ink-soft">No reviews yet.</p>
          )}
        </aside>
      </div>
    </>
  )
}

function RunCard({ run }: { run: AgentRunPublic }) {
  return (
    <Card className="p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        {run.deal ? (
          <Link to={`/deals/${run.deal.id}`} className="font-medium hover:underline">
            {run.deal.name}
          </Link>
        ) : (
          <span className="font-medium text-ink-soft">Deleted deal</span>
        )}
        <time dateTime={run.created_at} className="shrink-0 text-xs text-ink-faint">
          {timeAgo(run.created_at)}
        </time>
      </div>
      {run.status === "failed" ? (
        <p className="mt-2 flex items-center gap-1 text-red-600">
          <CircleAlert className="size-3.5" /> Review failed: {run.error}
        </p>
      ) : (
        run.summary && (
          <div className="mt-2 text-ink-soft">
            <RichText text={run.summary} />
          </div>
        )
      )}
      {(run.proposal_count ?? 0) > 0 && (
        <Badge tone="brand" className="mt-2">
          {run.proposal_count} {run.proposal_count === 1 ? "suggestion" : "suggestions"}
        </Badge>
      )}
    </Card>
  )
}
