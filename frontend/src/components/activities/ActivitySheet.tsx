import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"

import {
  activitiesCreateActivityMutation,
  activitiesDeleteActivityMutation,
  activitiesUpdateActivityMutation,
  contactsListContactsOptions,
  dealsListDealsOptions,
} from "@/client/@tanstack/react-query.gen"
import type { ActivityPublic, ActivityType, NamedRef } from "@/client/types.gen"
import { ACTIVITY_LABELS } from "@/lib/activities"
import { CompanySelect, OwnerSelect } from "@/components/records/fields"
import { changedFields, toId } from "@/lib/forms"
import { Button } from "@/components/ui/button"
import { Field, Select, Textarea } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Sheet, SheetFooter } from "@/components/ui/sheet"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { fromLocalInput, toLocalInput } from "@/lib/time"
import { useUnsavedChanges } from "@/lib/sheet"
import { useToast } from "@/lib/toast"

type Values = {
  type: ActivityType
  subject: string
  body: string
  due: string
  done: boolean
  deal_id: number | null
  contact_id: number | null
  company_id: number | null
  owner_id: number | null
}

/** Add an activity (a task by default), or edit one when `activity` is given. */
export function ActivitySheet({
  open,
  onClose,
  activity,
}: {
  open: boolean
  onClose: () => void
  activity?: ActivityPublic
}) {
  const title = activity ? `Edit ${ACTIVITY_LABELS[activity.type].toLowerCase()}` : "New activity"
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <ActivityForm key={`${open}-${activity?.id}`} activity={activity} onClose={onClose} />
    </Sheet>
  )
}

/** A record the activity links to, kept as an option even if the list doesn't include it. */
function withCurrent(options: NamedRef[], current: NamedRef | null | undefined) {
  return current && !options.some((o) => o.id === current.id) ? [current, ...options] : options
}

function ActivityForm({ activity, onClose }: { activity?: ActivityPublic; onClose: () => void }) {
  const { user } = useAuth()
  const { isAdmin } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [initial] = useState<Values>(() => ({
    type: activity?.type ?? "task",
    subject: activity?.subject ?? "",
    body: activity?.body ?? "",
    due: toLocalInput(activity?.due_at),
    done: activity?.done ?? false,
    deal_id: activity?.deal_id ?? null,
    contact_id: activity?.contact_id ?? null,
    company_id: activity?.company_id ?? null,
    owner_id: activity?.owner_id ?? user?.id ?? null,
  }))
  const [v, setV] = useState(initial)
  useUnsavedChanges(JSON.stringify(v) !== JSON.stringify(initial))
  const set = (patch: Partial<Values>) => setV({ ...v, ...patch })

  const deals = useQuery(dealsListDealsOptions({ query: { status: "open", limit: 200 } }))
  const contacts = useQuery(contactsListContactsOptions({ query: { limit: 200 } }))
  const dealOptions = withCurrent(
    (deals.data?.data ?? []).map((d) => ({ id: d.id, name: d.title })),
    activity?.deal,
  )
  const contactOptions = withCurrent(
    (contacts.data?.data ?? []).map((c) => ({
      id: c.id,
      name: [c.first_name, c.last_name].filter(Boolean).join(" "),
    })),
    activity?.contact,
  )

  const finish = (message: string) => {
    invalidate(queryClient, ...DEAL_QUERIES)
    toast(message)
    onClose()
  }
  const onError = (e: unknown) => setError(apiErrorMessage(e))
  const create = useMutation({
    ...activitiesCreateActivityMutation(),
    onSuccess: (a) => finish(`Added “${a.subject}”`),
    onError,
  })
  const update = useMutation({
    ...activitiesUpdateActivityMutation(),
    onSuccess: () => finish("Saved"),
    onError,
  })
  const remove = useMutation({
    ...activitiesDeleteActivityMutation(),
    onSuccess: () => finish("Deleted"),
    onError,
  })
  const saving = create.isPending || update.isPending
  const busy = saving || remove.isPending
  const isNote = v.type === "note"

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const body = {
      type: v.type,
      subject: v.subject.trim(),
      body: v.body.trim() || null,
      due_at: isNote ? null : fromLocalInput(v.due),
      done: isNote ? false : v.done,
      deal_id: v.deal_id,
      contact_id: v.contact_id,
      company_id: v.company_id,
      ...(isAdmin && v.owner_id ? { owner_id: v.owner_id } : {}),
    }
    if (!activity) return create.mutate({ body })
    const current = { ...activity, body: activity.body ?? null, due_at: activity.due_at ?? null }
    const changes = changedFields(body, current)
    // the same moment can come back from the server spelled differently
    if (
      changes.due_at !== undefined &&
      body.due_at &&
      current.due_at &&
      new Date(body.due_at).getTime() === new Date(current.due_at).getTime()
    ) {
      delete changes.due_at
    }
    if (Object.keys(changes).length === 0) return onClose()
    update.mutate({ path: { activity_id: activity.id }, body: changes })
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type" htmlFor="activity-type">
          <Select
            id="activity-type"
            value={v.type}
            onChange={(e) => set({ type: e.target.value as ActivityType })}
          >
            {Object.entries(ACTIVITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        {!isNote && (
          <Field label="Due" htmlFor="activity-due">
            <Input
              id="activity-due"
              type="datetime-local"
              value={v.due}
              onChange={(e) => set({ due: e.target.value })}
            />
          </Field>
        )}
      </div>
      <Field label={isNote ? "Title" : "Subject"} htmlFor="activity-subject">
        <Input
          id="activity-subject"
          required
          maxLength={255}
          autoFocus={!activity}
          placeholder={v.type === "task" ? "What needs doing?" : undefined}
          value={v.subject}
          onChange={(e) => set({ subject: e.target.value })}
        />
      </Field>
      <Field label="Details" htmlFor="activity-body">
        <Textarea
          id="activity-body"
          rows={4}
          value={v.body}
          onChange={(e) => set({ body: e.target.value })}
        />
      </Field>
      {!isNote && (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-brand-600"
            checked={v.done}
            onChange={(e) => set({ done: e.target.checked })}
          />
          {activity ? "Done" : "Already done (log it)"}
        </label>
      )}

      <fieldset className="space-y-3 border-t border-line pt-4">
        <legend className="sr-only">Linked to</legend>
        <p className="text-xs font-medium tracking-wide text-ink-faint uppercase">Linked to</p>
        <Field label="Deal" htmlFor="activity-deal">
          <Select
            id="activity-deal"
            value={v.deal_id ?? ""}
            onChange={(e) => {
              const deal_id = toId(e.target.value)
              const deal = deals.data?.data.find((d) => d.id === deal_id)
              // a deal brings its contact and company along, unless some are already picked
              set({
                deal_id,
                contact_id: v.contact_id ?? deal?.contact_id ?? null,
                company_id: v.company_id ?? deal?.company_id ?? null,
              })
            }}
          >
            <option value="">None</option>
            {dealOptions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Contact" htmlFor="activity-contact">
            <Select
              id="activity-contact"
              value={v.contact_id ?? ""}
              onChange={(e) => {
                const contact_id = toId(e.target.value)
                const contact = contacts.data?.data.find((c) => c.id === contact_id)
                set({ contact_id, company_id: v.company_id ?? contact?.company_id ?? null })
              }}
            >
              <option value="">None</option>
              {contactOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Company" htmlFor="activity-company">
            <CompanySelect
              id="activity-company"
              value={v.company_id}
              current={activity?.company}
              onChange={(company_id) => set({ company_id })}
            />
          </Field>
        </div>
        {isAdmin && (
          <Field label="Owner" htmlFor="activity-owner">
            <OwnerSelect
              id="activity-owner"
              value={v.owner_id}
              onChange={(owner_id) => set({ owner_id })}
            />
          </Field>
        )}
      </fieldset>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <SheetFooter>
        {activity && (
          <Button
            variant={confirmDelete ? "destructive" : "ghost"}
            className="mr-auto"
            disabled={busy}
            onClick={() =>
              confirmDelete
                ? remove.mutate({ path: { activity_id: activity.id } })
                : setConfirmDelete(true)
            }
          >
            {remove.isPending ? "Deleting…" : confirmDelete ? "Really delete?" : "Delete"}
          </Button>
        )}
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {saving ? "Saving…" : activity ? "Save" : "Add"}
        </Button>
      </SheetFooter>
    </form>
  )
}
