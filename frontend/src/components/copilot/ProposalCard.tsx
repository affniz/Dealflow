import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, CircleAlert, Sparkles, X } from "lucide-react"
import { Link } from "react-router-dom"

import {
  copilotApproveProposalMutation,
  copilotRejectProposalMutation,
} from "@/client/@tanstack/react-query.gen"
import type { AgentProposalPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/card"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { useToast } from "@/lib/toast"
import { cn } from "@/lib/utils"

/** A change an agent wants to make; nothing happens until someone approves it. */
export function ProposalCard({
  proposal,
  canDecide,
  showDeal = false,
}: {
  proposal: AgentProposalPublic
  canDecide: boolean
  showDeal?: boolean
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const onSettled = () =>
    invalidate(queryClient, ...DEAL_QUERIES, "copilotReadConversation", "copilotListProposals")
  const approve = useMutation({
    ...copilotApproveProposalMutation(),
    onSuccess: (p) =>
      p.status === "failed"
        ? toast(`Couldn't apply it: ${p.error}`, "error")
        : toast("Approved and applied"),
    onError: (e) => toast(apiErrorMessage(e), "error"),
    onSettled,
  })
  const reject = useMutation({
    ...copilotRejectProposalMutation(),
    onError: (e) => toast(apiErrorMessage(e), "error"),
    onSettled,
  })
  const busy = approve.isPending || reject.isPending
  const pending = proposal.status === "pending"

  return (
    <div
      className={cn(
        "rounded-lg border bg-surface p-3 text-sm",
        pending ? "border-brand-600/40 shadow-sm" : "border-line",
      )}
    >
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{proposal.summary}</p>
          {proposal.rationale && <p className="mt-1 text-ink-soft">{proposal.rationale}</p>}
          {showDeal && proposal.deal && (
            <Link
              to={`/deals/${proposal.deal.id}`}
              className="mt-1 inline-block text-xs text-brand-700 hover:underline"
            >
              {proposal.deal.name}
            </Link>
          )}
          {proposal.status === "failed" && proposal.error && (
            <p className="mt-1 flex items-center gap-1 text-red-600">
              <CircleAlert className="size-3.5" /> {proposal.error}
            </p>
          )}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-xs text-ink-faint">
          {proposal.source === "pipeline_agent" ? "Pipeline agent" : "Copilot"} suggestion
        </span>
        {pending ? (
          canDecide ? (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => reject.mutate({ path: { proposal_id: proposal.id } })}
              >
                <X /> Reject
              </Button>
              <Button
                size="sm"
                disabled={busy}
                onClick={() => approve.mutate({ path: { proposal_id: proposal.id } })}
              >
                <Check /> {approve.isPending ? "Applying…" : "Approve"}
              </Button>
            </div>
          ) : (
            <Badge>Waiting for approval</Badge>
          )
        ) : (
          <Badge
            tone={
              proposal.status === "approved"
                ? "success"
                : proposal.status === "failed"
                  ? "danger"
                  : "neutral"
            }
            className="capitalize"
          >
            {proposal.status === "approved" ? "Applied" : proposal.status}
          </Badge>
        )}
      </div>
    </div>
  )
}
