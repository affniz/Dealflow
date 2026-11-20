import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  pipelinesCreateLostReasonMutation,
  pipelinesListLostReasonsOptions,
  pipelinesUpdateLostReasonMutation,
} from "@/client/@tanstack/react-query.gen"
import { InlineInput } from "@/components/settings/InlineInput"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { apiErrorMessage, invalidate } from "@/lib/api"
import { useToast } from "@/lib/toast"
import { cn } from "@/lib/utils"

const QUERIES = ["pipelinesListLostReasons", "dashboardLostReasons"]

/** The reasons people pick when they mark a deal lost; they feed the dashboard's report. */
export function LostReasonSettings() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const reasons = useQuery(pipelinesListLostReasonsOptions({ query: { include_inactive: true } }))
  const [label, setLabel] = useState("")
  const onError = (e: unknown) => toast(apiErrorMessage(e), "error")
  const refresh = () => invalidate(queryClient, ...QUERIES)
  const update = useMutation({
    ...pipelinesUpdateLostReasonMutation(),
    onSuccess: (r) => {
      refresh()
      toast(`Saved “${r.label}”`)
    },
    onError,
  })
  const create = useMutation({
    ...pipelinesCreateLostReasonMutation(),
    onSuccess: (r) => {
      refresh()
      setLabel("")
      toast(`Added “${r.label}”`)
    },
    onError,
  })

  function add(e: FormEvent) {
    e.preventDefault()
    if (label.trim()) create.mutate({ body: { label: label.trim() } })
  }

  return (
    <section aria-labelledby="lost-reasons" className="space-y-4">
      <div>
        <h2 id="lost-reasons" className="text-base font-semibold">
          Lost reasons
        </h2>
        <p className="mt-1 text-sm text-ink-soft">
          What people choose from when they mark a deal lost. Turning a reason off hides it from
          that list but keeps it on deals already lost with it and in the dashboard's report.
        </p>
      </div>
      <Card>
        {reasons.isPending ? (
          <div className="p-4">
            <Spinner />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {reasons.data?.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-4 py-2">
                <InlineInput
                  key={r.label}
                  aria-label={`Name of “${r.label}”`}
                  value={r.label}
                  maxLength={100}
                  onSave={(v) => update.mutate({ path: { reason_id: r.id }, body: { label: v } })}
                  className={cn("flex-1", !r.is_active && "text-ink-faint")}
                />
                {!r.is_active && <Badge>Off</Badge>}
                <label className="flex shrink-0 items-center gap-2 text-sm text-ink-soft">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand-600"
                    checked={r.is_active ?? true}
                    disabled={update.isPending}
                    onChange={(e) =>
                      update.mutate({
                        path: { reason_id: r.id },
                        body: { is_active: e.target.checked },
                      })
                    }
                  />
                  In use
                </label>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={add} className="flex gap-2 border-t border-line p-3">
          <Input
            aria-label="New lost reason"
            placeholder="Add a reason, e.g. Timing"
            maxLength={100}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="h-8"
          />
          <Button type="submit" size="sm" disabled={!label.trim() || create.isPending}>
            <Plus /> Add
          </Button>
        </form>
      </Card>
    </section>
  )
}
