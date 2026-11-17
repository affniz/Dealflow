import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"

import { activitiesCreateActivityMutation } from "@/client/@tanstack/react-query.gen"
import type { ActivityType, DealPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { useToast } from "@/lib/toast"
import { cn } from "@/lib/utils"

const TYPES: { value: ActivityType; label: string }[] = [
  { value: "note", label: "Note" },
  { value: "call", label: "Call" },
  { value: "meeting", label: "Meeting" },
  { value: "task", label: "Task" },
]

/** Log a note, call or meeting, or schedule a task, on a deal. */
export function ActivityComposer({ deal }: { deal: DealPublic }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [type, setType] = useState<ActivityType>("note")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [due, setDue] = useState("")
  const create = useMutation({
    ...activitiesCreateActivityMutation(),
    onSuccess: () => {
      setSubject("")
      setBody("")
      setDue("")
      invalidate(queryClient, ...DEAL_QUERIES)
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const isNote = type === "note"
  const schedulable = type === "task" || type === "meeting"

  function submit(e: FormEvent) {
    e.preventDefault()
    // notes don't need a subject: use the first line of the text
    const firstLine = body.trim().split("\n")[0]?.slice(0, 120) ?? ""
    const finalSubject = (isNote ? subject || firstLine : subject).trim()
    if (!finalSubject) return
    create.mutate({
      body: {
        type,
        subject: finalSubject,
        body: body.trim() || null,
        due_at: schedulable && due ? new Date(due).toISOString() : null,
        // logging a call or meeting records something that already happened
        done: type === "call" || (type === "meeting" && !due),
        deal_id: deal.id,
        contact_id: deal.contact_id,
        company_id: deal.company_id,
      },
    })
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-line bg-surface p-3">
      <div role="tablist" aria-label="Activity type" className="mb-3 flex gap-1">
        {TYPES.map((t) => (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={type === t.value}
            onClick={() => setType(t.value)}
            className={cn(
              "rounded-md px-3 py-1 text-sm font-medium",
              type === t.value ? "bg-brand-50 text-brand-700" : "text-ink-soft hover:bg-muted",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {!isNote && (
        <Input
          aria-label="Subject"
          placeholder={
            type === "task"
              ? "What needs doing?"
              : `${type === "call" ? "Call" : "Meeting"} summary`
          }
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          maxLength={255}
          required
          className="mb-2"
        />
      )}
      <Textarea
        aria-label={isNote ? "Note" : "Details"}
        placeholder={isNote ? "Write a note…" : "Details (optional)"}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={isNote ? 3 : 2}
        required={isNote}
      />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        {schedulable ? (
          <label className="flex items-center gap-2 text-sm text-ink-soft">
            {type === "task" ? "Due" : "When"}
            <Input
              type="datetime-local"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="w-auto"
            />
          </label>
        ) : (
          <span />
        )}
        <Button type="submit" size="sm" disabled={create.isPending}>
          {create.isPending
            ? "Saving…"
            : isNote
              ? "Add note"
              : type === "task"
                ? "Add task"
                : `Log ${type}`}
        </Button>
      </div>
    </form>
  )
}
