import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Briefcase, Building2, ListChecks, RotateCcw, Trash2, User } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import {
  trashDeleteForGoodMutation,
  trashListTrashOptions,
  trashRestoreMutation,
} from "@/client/@tanstack/react-query.gen"
import type { TrashItem } from "@/client/types.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm"
import { RECORD_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { formatDateTime } from "@/lib/time"
import { useToast } from "@/lib/toast"
import { timeAgo } from "@/lib/utils"

const TYPES = {
  deal: { label: "Deal", icon: Briefcase, path: (id: number) => `/deals/${id}` },
  contact: { label: "Contact", icon: User, path: (id: number) => `/contacts/${id}` },
  company: { label: "Company", icon: Building2, path: (id: number) => `/companies/${id}` },
  activity: { label: "Activity", icon: ListChecks, path: () => "/activities" },
} as const

/** Deleted records, restorable until they're deleted for good. */
export function TrashPage() {
  const { user } = useAuth()
  const { isAdmin, seesTeam } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const trash = useQuery(trashListTrashOptions())
  const [purging, setPurging] = useState<TrashItem | null>(null)

  const restore = useMutation({
    ...trashRestoreMutation(),
    onSuccess: (_, vars) => {
      invalidate(queryClient, ...RECORD_QUERIES)
      const item = trash.data?.find(
        (i) => i.type === vars.path.record_type && i.id === vars.path.record_id,
      )
      toast(`Restored “${item?.name ?? "it"}”`)
      if (item) navigate(TYPES[item.type].path(item.id))
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const purge = useMutation({
    ...trashDeleteForGoodMutation(),
    onSuccess: () => {
      invalidate(queryClient, "trashListTrash")
      toast("Deleted for good")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })

  return (
    <>
      <PageHeader title="Recently deleted" />
      <div className="max-w-4xl space-y-4 px-4 pb-8 md:px-6">
        <p className="text-sm text-ink-soft">
          Deleted deals, contacts, companies and activities stay here for 30 days. Restoring one
          brings back its history and its links to other records.
          {seesTeam ? " This lists the whole team's." : " This lists yours."}
        </p>
        <Card>
          {trash.isPending ? (
            <div className="p-4">
              <Spinner />
            </div>
          ) : !trash.data?.length ? (
            <p className="p-6 text-center text-sm text-ink-faint">Nothing deleted lately.</p>
          ) : (
            <ul className="divide-y divide-line">
              {trash.data.map((item) => {
                const { label, icon: Icon } = TYPES[item.type]
                return (
                  <li
                    key={`${item.type}-${item.id}`}
                    className="flex flex-wrap items-center gap-3 px-4 py-3"
                  >
                    <span
                      className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-ink-soft [&_svg]:size-4"
                      aria-hidden
                    >
                      <Icon />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{item.name}</p>
                      <p className="text-xs text-ink-soft">
                        {label} · deleted {timeAgo(item.deleted_at)}
                        {item.deleted_by && ` by ${item.deleted_by.name}`} · gone for good{" "}
                        {formatDateTime(item.purge_after)}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={restore.isPending}
                      aria-label={`Restore ${item.name}`}
                      onClick={() =>
                        restore.mutate({ path: { record_type: item.type, record_id: item.id } })
                      }
                    >
                      <RotateCcw /> Restore
                    </Button>
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${item.name} for good`}
                        onClick={() => setPurging(item)}
                      >
                        <Trash2 /> Delete for good
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      </div>
      <ConfirmDialog
        open={purging !== null}
        onClose={() => setPurging(null)}
        onConfirm={() =>
          purging &&
          purge.mutate(
            { path: { record_type: purging.type, record_id: purging.id } },
            { onSettled: () => setPurging(null) },
          )
        }
        busy={purge.isPending}
        title={`Delete “${purging?.name ?? ""}” for good?`}
        description="It can't be restored after this. Its history goes too, and other records lose their link to it."
        confirmLabel="Delete for good"
      />
    </>
  )
}
