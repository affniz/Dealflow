import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { dealsCreateDealMutation } from "@/client/@tanstack/react-query.gen"
import type { StagePublic } from "@/client/types.gen"
import { DealForm } from "@/components/deals/DealForm"
import { Dialog } from "@/components/ui/dialog"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { useToast } from "@/lib/toast"

export function NewDealDialog({
  open,
  onClose,
  stages,
}: {
  open: boolean
  onClose: () => void
  stages: StagePublic[]
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const create = useMutation({
    ...dealsCreateDealMutation(),
    onSuccess: (deal) => {
      invalidate(queryClient, ...DEAL_QUERIES)
      toast(`Added “${deal.title}”`)
      onClose()
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  return (
    <Dialog open={open} onClose={onClose} title="New deal">
      <DealForm
        key={String(open)}
        initial={{
          title: "",
          value: "",
          stage_id: stages[0]?.id ?? null,
          company_id: null,
          contact_id: null,
          owner_id: user?.id ?? null,
          expected_close_date: null,
        }}
        stages={stages}
        canAssign={permissions(user).isAdmin}
        busy={create.isPending}
        error={error}
        submitLabel="Add deal"
        onCancel={onClose}
        onSubmit={(v) => {
          setError(null)
          create.mutate({
            body: {
              title: v.title.trim(),
              value: v.value || "0",
              stage_id: v.stage_id!,
              company_id: v.company_id,
              contact_id: v.contact_id,
              owner_id: v.owner_id,
              expected_close_date: v.expected_close_date,
            },
          })
        }}
      />
    </Dialog>
  )
}
