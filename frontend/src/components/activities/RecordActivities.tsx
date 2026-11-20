import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { activitiesListActivitiesOptions } from "@/client/@tanstack/react-query.gen"
import type { ActivityPublic } from "@/client/types.gen"
import { ActivityComposer, type ActivityLinks } from "@/components/activities/ActivityComposer"
import { ActivityItem } from "@/components/activities/ActivityItem"
import { ActivitySheet } from "@/components/activities/ActivitySheet"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"

const PAGE = 20

/**
 * The activity block of a contact or company page: log something, what's still to do (soonest
 * first) and what has happened (newest first).
 */
export function RecordActivities({
  filter,
  links,
  hide,
  canWrite,
}: {
  filter: { contact_id: number } | { company_id: number }
  links: ActivityLinks
  hide: ("contact" | "company")[]
  canWrite: boolean
}) {
  const [historyLimit, setHistoryLimit] = useState(PAGE)
  const [editing, setEditing] = useState<ActivityPublic | null>(null)
  const todo = useQuery(
    activitiesListActivitiesOptions({ query: { ...filter, todo: true, limit: 100 } }),
  )
  const history = useQuery({
    ...activitiesListActivitiesOptions({
      query: { ...filter, todo: false, sort: "recent", limit: historyLimit },
    }),
    placeholderData: (previous) => previous,
  })

  const item = (a: ActivityPublic) => (
    <ActivityItem
      key={a.id}
      activity={a}
      canWrite={canWrite}
      showOwner
      hide={hide}
      onOpen={canWrite ? setEditing : undefined}
    />
  )

  return (
    <section className="space-y-4" aria-label="Activity">
      {canWrite && <ActivityComposer links={links} />}

      <div>
        <h2 className="mb-2 text-sm font-semibold">
          To do{todo.data && todo.data.count > 0 ? ` · ${todo.data.count}` : ""}
        </h2>
        {todo.isPending ? (
          <Spinner />
        ) : todo.data && todo.data.count > 0 ? (
          <Card>
            <ul className="divide-y divide-line">{todo.data.data.map(item)}</ul>
          </Card>
        ) : (
          <p className="text-sm text-ink-faint">Nothing scheduled.</p>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold">History</h2>
        {history.isPending ? (
          <Spinner />
        ) : history.data && history.data.count > 0 ? (
          <Card>
            <ul className="divide-y divide-line">{history.data.data.map(item)}</ul>
            {history.data.count > history.data.data.length && historyLimit < 200 && (
              <div className="border-t border-line p-2 text-center">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={history.isFetching}
                  onClick={() => setHistoryLimit((n) => Math.min(n + PAGE, 200))}
                >
                  Show more
                </Button>
              </div>
            )}
          </Card>
        ) : (
          <p className="text-sm text-ink-faint">No calls, meetings or notes yet.</p>
        )}
      </div>

      <ActivitySheet
        open={editing !== null}
        activity={editing ?? undefined}
        onClose={() => setEditing(null)}
      />
    </section>
  )
}
