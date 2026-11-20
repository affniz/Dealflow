import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useCallback, useState } from "react"

import { activitiesListActivitiesOptions } from "@/client/@tanstack/react-query.gen"
import type {
  ActivitiesListActivitiesData,
  ActivityPublic,
  ActivityType,
  PageActivityPublic,
} from "@/client/types.gen"
import { ActivityItem } from "@/components/activities/ActivityItem"
import { ACTIVITY_LABELS } from "@/lib/activities"
import { ActivitySheet } from "@/components/activities/ActivitySheet"
import { PageHeader } from "@/components/layout/AppLayout"
import { OwnerFilter } from "@/components/records/filters"
import { ownerQuery } from "@/lib/forms"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { EmptyState, Pager, SearchBox } from "@/components/ui/list"
import { useListParams } from "@/lib/listParams"
import { permissions, useAuth } from "@/lib/auth"
import { startOfTomorrow, useNow } from "@/lib/time"
import { cn } from "@/lib/utils"

type Query = NonNullable<ActivitiesListActivitiesData["query"]>
type SectionKey = "overdue" | "today" | "upcoming" | "undated"

const SECTION_STEP = 20
const MAX_LIMIT = 200 // the API's page size limit
const HISTORY_PAGE = 50
const TODO_TYPES: ActivityType[] = ["task", "call", "meeting", "email"]
const HISTORY_TYPES: ActivityType[] = [...TODO_TYPES, "note"]

/** Your to-dos grouped by when they're due, and what you've done and noted. */
export function ActivitiesPage() {
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const { params, set, page } = useListParams()
  const [editing, setEditing] = useState<ActivityPublic | "new" | null>(null)
  const tab = params.get("tab") === "history" ? "history" : "todo"
  // writers start with their own list; viewers own nothing, so they start with everyone's
  const defaultOwner = canWrite ? "me" : "all"
  const owner = seesTeam ? (params.get("owner") ?? defaultOwner) : "me"
  const types = tab === "todo" ? TODO_TYPES : HISTORY_TYPES
  const typeParam = params.get("type") as ActivityType | null
  const type = typeParam && types.includes(typeParam) ? typeParam : undefined
  const q = params.get("q") ?? ""
  const onSearch = useCallback((value: string) => set({ q: value }), [set])

  const base: Query = {
    owner_id: ownerQuery(owner, user?.id),
    type,
    q: q || undefined,
  }
  const filtered = Boolean(type || q)
  const open = (a: ActivityPublic) => setEditing(a)

  return (
    <>
      <PageHeader title={owner === "me" ? "My activities" : "Activities"}>
        {canWrite && (
          <Button onClick={() => setEditing("new")}>
            <Plus /> New activity
          </Button>
        )}
      </PageHeader>
      <div className="space-y-3 px-4 pb-6 md:px-6">
        <div role="tablist" aria-label="Show" className="flex gap-1 border-b border-line">
          {(
            [
              ["todo", "To do"],
              ["history", "Done & notes"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={tab === value}
              onClick={() => set({ tab: value === "todo" ? null : value })}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
                tab === value
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-ink-soft hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <SearchBox
            label="Search activities"
            placeholder="Search subject and details"
            value={q}
            onChange={onSearch}
          />
          {seesTeam && (
            <OwnerFilter
              value={owner}
              onChange={(v) => set({ owner: v === defaultOwner ? null : v })}
            />
          )}
          <div className="flex flex-wrap gap-1" role="group" aria-label="Type">
            {[undefined, ...types].map((t) => (
              <button
                key={t ?? "all"}
                type="button"
                aria-pressed={type === t}
                onClick={() => set({ type: t ?? null })}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium",
                  type === t
                    ? "border-brand-600 bg-brand-50 text-brand-700"
                    : "border-line text-ink-soft hover:bg-muted",
                )}
              >
                {t ? `${ACTIVITY_LABELS[t]}s` : "All"}
              </button>
            ))}
          </div>
        </div>

        {tab === "todo" ? (
          <TodoList
            base={base}
            canWrite={canWrite}
            showOwner={owner !== "me"}
            filtered={filtered}
            onOpen={canWrite ? open : undefined}
          />
        ) : (
          <HistoryList
            base={base}
            page={page}
            onPage={(p) => set({ page: p === 1 ? null : p })}
            canWrite={canWrite}
            showOwner={owner !== "me"}
            filtered={filtered}
            onOpen={canWrite ? open : undefined}
          />
        )}
      </div>
      <ActivitySheet
        open={editing !== null}
        activity={editing === "new" || editing === null ? undefined : editing}
        onClose={() => setEditing(null)}
      />
    </>
  )
}

type ListProps = {
  base: Query
  canWrite: boolean
  showOwner: boolean
  filtered: boolean
  onOpen?: (a: ActivityPublic) => void
}

function TodoList({ base, canWrite, showOwner, filtered, onOpen }: ListProps) {
  // "today" is the reader's today, so the boundaries come from the browser's clock and zone.
  // They're fixed at `cutoff` (so the queries don't change every tick) and moved on when an item
  // in Today comes due or the day ends, which refetches the groups.
  const now = useNow()
  const [cutoff, setCutoff] = useState(now)
  const nowIso = new Date(cutoff).toISOString()
  const tomorrowIso = startOfTomorrow(cutoff).toISOString()
  const [limits, setLimits] = useState<Record<SectionKey, number>>({
    overdue: SECTION_STEP,
    today: SECTION_STEP,
    upcoming: SECTION_STEP,
    undated: SECTION_STEP,
  })

  const sections: { key: SectionKey; title: string; query: Query; danger?: boolean }[] = [
    { key: "overdue", title: "Overdue", query: { due_before: nowIso }, danger: true },
    { key: "today", title: "Today", query: { due_after: nowIso, due_before: tomorrowIso } },
    { key: "upcoming", title: "Upcoming", query: { due_after: tomorrowIso } },
    { key: "undated", title: "No due date", query: { has_due: false } },
  ]
  const results = [
    useSection(base, sections[0]!.query, limits.overdue),
    useSection(base, sections[1]!.query, limits.today),
    useSection(base, sections[2]!.query, limits.upcoming),
    useSection(base, sections[3]!.query, limits.undated),
  ]
  const dayEnded = now >= startOfTomorrow(cutoff).getTime()
  const somethingCameDue = results[1]!.data?.data.some(
    (a) => a.due_at && new Date(a.due_at).getTime() <= now,
  )
  if ((dayEnded || somethingCameDue) && cutoff !== now) setCutoff(now)

  if (results.some((r) => r.isPending)) {
    return (
      <div className="grid place-items-center p-12">
        <Spinner />
      </div>
    )
  }
  if (results.some((r) => r.isError)) {
    return (
      <Card>
        <EmptyState title="Couldn't load activities.">Try reloading the page.</EmptyState>
      </Card>
    )
  }
  if (results.every((r) => r.data?.count === 0)) {
    return (
      <Card>
        {filtered ? (
          <EmptyState title="Nothing matches.">Try a different search or type.</EmptyState>
        ) : (
          <EmptyState title="You're all caught up.">
            Tasks, calls and meetings you schedule show up here.
          </EmptyState>
        )}
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      {sections.map((section, i) => {
        const result = results[i]!
        const data = result.data as PageActivityPublic
        if (data.count === 0) return null
        const limit = limits[section.key]
        return (
          <section key={section.key} aria-labelledby={`section-${section.key}`}>
            <h2
              id={`section-${section.key}`}
              className={cn(
                "mb-2 text-sm font-semibold",
                section.danger && "text-red-600 dark:text-red-400",
              )}
            >
              {section.title} <span className="font-normal text-ink-faint">· {data.count}</span>
            </h2>
            <Card>
              <ul className="divide-y divide-line">
                {data.data.map((a) => (
                  <ActivityItem
                    key={a.id}
                    activity={a}
                    canWrite={canWrite}
                    showOwner={showOwner}
                    onOpen={onOpen}
                  />
                ))}
              </ul>
              {data.count > data.data.length && limit < MAX_LIMIT && (
                <div className="border-t border-line p-2 text-center">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={result.isFetching}
                    onClick={() =>
                      setLimits({
                        ...limits,
                        [section.key]: Math.min(limit + SECTION_STEP, MAX_LIMIT),
                      })
                    }
                  >
                    Show {Math.min(SECTION_STEP, data.count - data.data.length)} more
                  </Button>
                </div>
              )}
            </Card>
          </section>
        )
      })}
    </div>
  )
}

function useSection(base: Query, query: Query, limit: number) {
  return useQuery({
    ...activitiesListActivitiesOptions({ query: { ...base, ...query, todo: true, limit } }),
    placeholderData: keepPreviousData,
  })
}

function HistoryList({
  base,
  page,
  onPage,
  canWrite,
  showOwner,
  filtered,
  onOpen,
}: ListProps & { page: number; onPage: (page: number) => void }) {
  const history = useQuery({
    ...activitiesListActivitiesOptions({
      query: {
        ...base,
        todo: false,
        sort: "recent",
        skip: (page - 1) * HISTORY_PAGE,
        limit: HISTORY_PAGE,
      },
    }),
    placeholderData: keepPreviousData,
  })

  if (history.isPending) {
    return (
      <div className="grid place-items-center p-12">
        <Spinner />
      </div>
    )
  }
  if (history.isError) {
    return (
      <Card>
        <EmptyState title="Couldn't load activities.">Try reloading the page.</EmptyState>
      </Card>
    )
  }
  return (
    <>
      <Card className={cn(history.isPlaceholderData && "opacity-60")}>
        {history.data.count === 0 ? (
          filtered ? (
            <EmptyState title="Nothing matches.">Try a different search or type.</EmptyState>
          ) : (
            <EmptyState title="Nothing here yet.">
              Finished tasks, logged calls and notes show up here.
            </EmptyState>
          )
        ) : (
          <ul className="divide-y divide-line">
            {history.data.data.map((a) => (
              <ActivityItem
                key={a.id}
                activity={a}
                canWrite={canWrite}
                showOwner={showOwner}
                onOpen={onOpen}
              />
            ))}
          </ul>
        )}
      </Card>
      <Pager page={page} pageSize={HISTORY_PAGE} count={history.data.count} onPage={onPage} />
    </>
  )
}
