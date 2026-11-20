import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  ArrowRight,
  Bot,
  CalendarClock,
  CircleCheck,
  CircleX,
  Flame,
  PencilLine,
  Plus,
  RotateCcw,
  Sparkles,
} from "lucide-react"
import { type ReactNode, useState } from "react"

import { activitiesUpdateActivityMutation } from "@/client/@tanstack/react-query.gen"
import type { ActivityPublic, DealEventPublic, TimelineItem } from "@/client/types.gen"
import { ActivitySheet } from "@/components/activities/ActivitySheet"
import { ACTIVITY_ICONS } from "@/lib/activities"
import { DEAL_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { useNow } from "@/lib/time"
import { useToast } from "@/lib/toast"
import { cn, formatMoney, timeAgo } from "@/lib/utils"
import { VIA_LABELS } from "@/lib/sources"

const FIELD_LABELS: Record<string, string> = {
  expected_close_date: "expected close date",
  contact_id: "contact",
  company_id: "company",
  owner_id: "owner",
  custom_fields: "custom fields",
}

export function Timeline({
  items,
  stageName,
  canWrite,
}: {
  items: TimelineItem[]
  stageName: (id: unknown) => string
  canWrite: boolean
}) {
  const [editing, setEditing] = useState<ActivityPublic | null>(null)
  if (items.length === 0) return <p className="text-sm text-ink-faint">Nothing here yet.</p>
  return (
    <>
      <ol className="relative space-y-5 before:absolute before:top-2 before:bottom-2 before:left-4 before:w-px before:bg-line">
        {items.map((item) =>
          item.kind === "event" && item.event ? (
            <EventRow
              key={`e${item.event.id}`}
              event={item.event}
              actor={item.actor?.name}
              stageName={stageName}
            />
          ) : item.activity ? (
            <ActivityRow
              key={`a${item.activity.id}`}
              activity={item.activity}
              actor={item.actor?.name}
              canWrite={canWrite}
              onOpen={setEditing}
            />
          ) : null,
        )}
      </ol>
      <ActivitySheet
        open={editing !== null}
        activity={editing ?? undefined}
        onClose={() => setEditing(null)}
      />
    </>
  )
}

function Row({
  icon,
  tone,
  children,
}: {
  icon: ReactNode
  tone?: "danger" | "success"
  children: ReactNode
}) {
  return (
    <li className="relative flex gap-3">
      <span
        className={cn(
          "relative z-10 grid size-8 shrink-0 place-items-center rounded-full border border-line bg-surface text-ink-soft [&_svg]:size-4",
          tone === "danger" &&
            "border-red-200 bg-red-50 text-red-600 dark:border-red-900 dark:bg-red-950",
          tone === "success" &&
            "border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-900 dark:bg-emerald-950",
        )}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1 pt-1">{children}</div>
    </li>
  )
}

function ViaBadge({ via }: { via: string }) {
  return (
    <span className="ml-1.5 inline-flex items-center gap-1 rounded-full bg-brand-50 px-1.5 py-0.5 align-middle text-[11px] font-medium text-brand-700">
      <Sparkles className="size-3" aria-hidden />
      {VIA_LABELS[via] ?? `via ${via.replaceAll("_", " ")}`}
    </span>
  )
}

function When({ at }: { at: string }) {
  return (
    <time dateTime={at} title={new Date(at).toLocaleString()} className="text-xs text-ink-faint">
      {timeAgo(at)}
    </time>
  )
}

function EventRow({
  event,
  actor,
  stageName,
}: {
  event: DealEventPublic
  actor?: string
  stageName: (id: unknown) => string
}) {
  const who = actor ?? "Dealflow"
  const d = event.data
  let icon: ReactNode = <PencilLine />
  let tone: "danger" | "success" | undefined
  let text: ReactNode
  switch (event.kind) {
    case "created":
      icon = <Plus />
      text = <>created this deal in {stageName(d.stage_id)}</>
      break
    case "stage_changed":
      icon = <ArrowRight />
      text = (
        <>
          moved it from {stageName(d.from_stage_id)} to{" "}
          <strong className="font-medium">{stageName(d.to_stage_id)}</strong>
        </>
      )
      break
    case "updated":
      text = (
        <>updated {((d.fields as string[]) ?? []).map((f) => FIELD_LABELS[f] ?? f).join(", ")}</>
      )
      break
    case "won":
      icon = <CircleCheck />
      tone = "success"
      text = <>marked it as won ({formatMoney(d.value as string)})</>
      break
    case "lost":
      icon = <CircleX />
      tone = "danger"
      text = (
        <>
          marked it as lost: <strong className="font-medium">{String(d.reason)}</strong>
          {d.note ? <span className="mt-1 block text-ink-soft">“{String(d.note)}”</span> : null}
        </>
      )
      break
    case "reopened":
      icon = <RotateCcw />
      text = <>reopened it</>
      break
    case "rotting":
      icon = <Flame />
      tone = "danger"
      text = (
        <>
          flagged it as stalled: {String(d.days_in_stage)} days in {stageName(d.stage_id)} (limit{" "}
          {String(d.rotting_days)})
        </>
      )
      break
    default:
      icon = actor ? <PencilLine /> : <Bot />
      text = <>{event.kind.replaceAll("_", " ")}</>
  }
  return (
    <Row icon={icon} tone={tone}>
      <p className="text-sm">
        <span className="font-medium">{who}</span> {text}
        {typeof d.via === "string" && <ViaBadge via={d.via} />}
      </p>
      <When at={event.created_at} />
    </Row>
  )
}

function ActivityRow({
  activity,
  actor,
  canWrite,
  onOpen,
}: {
  activity: ActivityPublic
  actor?: string
  canWrite: boolean
  onOpen: (activity: ActivityPublic) => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const Icon = ACTIVITY_ICONS[activity.type]
  const toggle = useMutation({
    ...activitiesUpdateActivityMutation(),
    onSuccess: () => invalidate(queryClient, ...DEAL_QUERIES),
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const now = useNow()
  const overdue = !activity.done && activity.due_at && new Date(activity.due_at).getTime() < now
  // the same rule as ActivityItem: to-dos and anything scheduled can be ticked off; logged
  // calls and meetings and notes already happened
  const checkable =
    activity.type !== "note" &&
    (!activity.done || activity.type === "task" || Boolean(activity.due_at))

  return (
    <Row icon={<Icon />}>
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="flex items-start gap-2">
          {checkable && (
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-brand-600"
              checked={activity.done}
              disabled={!canWrite || toggle.isPending}
              aria-label={activity.done ? "Mark as not done" : "Mark as done"}
              onChange={(e) =>
                toggle.mutate({
                  path: { activity_id: activity.id },
                  body: { done: e.target.checked },
                })
              }
            />
          )}
          <div className="min-w-0 flex-1">
            <button
              type="button"
              disabled={!canWrite}
              onClick={() => onOpen(activity)}
              className={cn(
                "text-left text-sm font-medium enabled:hover:text-brand-700 enabled:hover:underline",
                activity.done && checkable && "text-ink-soft line-through",
              )}
            >
              {activity.subject}
            </button>
            {activity.body && (
              <p className="mt-1 text-sm whitespace-pre-line text-ink-soft">{activity.body}</p>
            )}
            {activity.due_at && (
              <p
                className={cn(
                  "mt-1 flex items-center gap-1 text-xs",
                  overdue ? "text-red-600" : "text-ink-faint",
                )}
              >
                <CalendarClock className="size-3.5" />
                {overdue ? "Overdue · " : "Due "}
                {new Date(activity.due_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
            )}
          </div>
        </div>
      </div>
      <p className="mt-1 text-xs text-ink-faint">
        {actor ?? "Someone"} · {activity.type} · <When at={activity.created_at} />
        {activity.via && <ViaBadge via={activity.via} />}
      </p>
    </Row>
  )
}
