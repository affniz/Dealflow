import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Building2, CalendarClock, Handshake, Sparkles, User } from "lucide-react"
import { Link } from "react-router-dom"

import { activitiesUpdateActivityMutation } from "@/client/@tanstack/react-query.gen"
import type { ActivityPublic } from "@/client/types.gen"
import { ACTIVITY_ICONS } from "@/lib/activities"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { formatDateTime, useNow } from "@/lib/time"
import { useToast } from "@/lib/toast"
import { cn, timeAgo } from "@/lib/utils"

const VIA_LABELS: Record<string, string> = {
  copilot: "via Copilot",
  pipeline_agent: "via Pipeline agent",
  auto_reminder: "Automatic reminder",
}

type LinkKind = "deal" | "contact" | "company"

/**
 * One activity in a list: tick it off, open it to edit, follow its links.
 * `hide` leaves out links that are obvious from the page (the contact on a contact page).
 */
export function ActivityItem({
  activity: a,
  canWrite,
  showOwner,
  hide = [],
  onOpen,
}: {
  activity: ActivityPublic
  canWrite: boolean
  showOwner?: boolean
  hide?: LinkKind[]
  onOpen?: (activity: ActivityPublic) => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const now = useNow()
  const toggle = useMutation({
    ...activitiesUpdateActivityMutation(),
    onSuccess: (saved) => {
      invalidate(queryClient, ...DEAL_QUERIES)
      if (saved.done) toast(`Done: ${saved.subject}`)
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const Icon = ACTIVITY_ICONS[a.type]
  const isNote = a.type === "note"
  // to-dos and anything that was scheduled can be ticked off (or reopened); a logged call or
  // meeting and a note already happened, so they just show their type
  const checkable = !isNote && (!a.done || a.type === "task" || Boolean(a.due_at))
  const overdue = !a.done && a.due_at && new Date(a.due_at).getTime() < now
  const links = (
    [
      ["deal", a.deal, Handshake, "/deals/"],
      ["contact", a.contact, User, "/contacts/"],
      ["company", a.company, Building2, "/companies/"],
    ] as const
  ).filter(([kind, ref]) => ref && !hide.includes(kind))

  return (
    <li className="flex gap-3 px-4 py-3">
      {!checkable ? (
        <span className="grid size-4 shrink-0 place-items-center pt-0.5 text-ink-faint">
          <Icon className="size-4" aria-label={a.type} />
        </span>
      ) : (
        <input
          type="checkbox"
          className="mt-0.5 size-4 shrink-0 accent-brand-600"
          checked={a.done}
          disabled={!canWrite || toggle.isPending}
          aria-label={a.done ? `Mark “${a.subject}” as not done` : `Mark “${a.subject}” as done`}
          onChange={(e) =>
            toggle.mutate({ path: { activity_id: a.id }, body: { done: e.target.checked } })
          }
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          {checkable && <Icon className="mt-0.5 size-4 shrink-0 text-ink-faint" aria-hidden />}
          <button
            type="button"
            onClick={() => onOpen?.(a)}
            disabled={!onOpen}
            className={cn(
              "min-w-0 text-left text-sm font-medium enabled:hover:text-brand-700 enabled:hover:underline",
              a.done && checkable && "text-ink-soft line-through",
            )}
          >
            {a.subject}
          </button>
        </div>
        {a.body && a.body !== a.subject && (
          <p className="mt-0.5 line-clamp-2 text-sm whitespace-pre-line text-ink-soft">{a.body}</p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-faint">
          {a.due_at && !a.done && (
            <span className={cn("flex items-center gap-1", overdue && "font-medium text-red-600")}>
              <CalendarClock className="size-3.5" />
              {overdue ? "Overdue · " : "Due "}
              {formatDateTime(a.due_at)}
            </span>
          )}
          {(a.done || isNote) && (
            <time
              dateTime={a.done_at ?? a.created_at}
              title={formatDateTime(a.done_at ?? a.created_at)}
            >
              {isNote ? "Added" : checkable ? "Done" : "Logged"}{" "}
              {timeAgo(a.done_at ?? a.created_at)}
            </time>
          )}
          {links.map(([kind, ref, LinkIcon, base]) => (
            <Link
              key={kind}
              to={`${base}${ref!.id}`}
              className="flex max-w-56 items-center gap-1 truncate hover:text-ink hover:underline"
            >
              <LinkIcon className="size-3.5 shrink-0" />
              <span className="truncate">{ref!.name}</span>
            </Link>
          ))}
          {showOwner && a.owner && <span>{a.owner.name}</span>}
          {a.via && (
            <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">
              <Sparkles className="size-3" aria-hidden />
              {VIA_LABELS[a.via] ?? `via ${a.via.replaceAll("_", " ")}`}
            </span>
          )}
        </div>
      </div>
    </li>
  )
}
