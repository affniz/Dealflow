import { useQuery } from "@tanstack/react-query"
import { CircleAlert, CircleCheck } from "lucide-react"

import { systemReadStatusOptions } from "@/client/@tanstack/react-query.gen"
import type { JobRunPublic, JobStatus } from "@/client/types.gen"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { formatDateTime } from "@/lib/time"
import { timeAgo } from "@/lib/utils"

const STATUS: Record<JobStatus, { label: string; tone: "neutral" | "danger" | "success" }> = {
  running: { label: "Running", tone: "neutral" },
  succeeded: { label: "Worked", tone: "success" },
  warning: { label: "Problem", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
  skipped: { label: "Nothing to do", tone: "neutral" },
}

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge tone={STATUS[status].tone}>{STATUS[status].label}</Badge>
}

/** What a run did, in a few words, from the counts the job returned. */
function summary(run: JobRunPublic) {
  if (run.error) return run.error
  return Object.entries(run.result)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
    .join(" · ")
}

/** Admins: whether the background jobs are running and working. */
export function SystemSettings() {
  const status = useQuery({ ...systemReadStatusOptions(), refetchInterval: 60_000 })
  if (status.isPending) return <Spinner />
  if (status.isError) return <p className="text-sm text-red-600">Couldn't load the status.</p>
  const { problems, jobs, recent_runs: recent, sentry, emails } = status.data

  return (
    <div className="space-y-8">
      <section aria-labelledby="system-health" className="space-y-3">
        <h2 id="system-health" className="text-base font-semibold">
          Background jobs
        </h2>
        {problems.length > 0 ? (
          <ul className="space-y-2" aria-label="Needs attention">
            {problems.map((p) => (
              <li
                key={p}
                className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200"
              >
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                <span className="break-words">{p}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-center gap-2 text-sm text-ink-soft">
            <CircleCheck className="size-4 text-emerald-600" /> Everything is working.
          </p>
        )}
        <Card>
          <ul className="divide-y divide-line">
            {jobs.map((job) => (
              <li key={job.job} className="flex flex-wrap items-start gap-x-4 gap-y-1 p-4">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{job.name}</div>
                  <div className="text-xs text-ink-faint">{job.schedule}</div>
                </div>
                <div className="text-right text-xs text-ink-soft">
                  {job.last_run ? (
                    <>
                      <div className="flex items-center justify-end gap-2">
                        <StatusBadge status={job.last_run.status} />
                        <span title={formatDateTime(job.last_run.started_at)}>
                          {timeAgo(job.last_run.started_at)}
                        </span>
                      </div>
                      <div className="mt-1">
                        {job.last_success_at
                          ? `Last worked ${timeAgo(job.last_success_at)}`
                          : "Hasn't worked yet"}
                      </div>
                    </>
                  ) : (
                    "Hasn't run yet"
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <p className="text-xs text-ink-faint">
          {emails
            ? "When a job starts failing, the owner and admins get an email."
            : "Set up email (SMTP) to have the owner and admins emailed when a job starts failing."}{" "}
          {sentry
            ? "Errors are reported to Sentry."
            : "Set SENTRY_DSN to have errors reported to Sentry."}
        </p>
      </section>

      <section aria-labelledby="system-runs" className="space-y-3">
        <h2 id="system-runs" className="text-base font-semibold">
          Recent runs
        </h2>
        <Card>
          {recent.length === 0 ? (
            <p className="p-6 text-center text-sm text-ink-faint">
              No jobs have run yet. They run in the background worker (see the README).
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {recent.map((run) => (
                <li key={run.id} className="flex items-start gap-3 px-4 py-3 text-sm">
                  <StatusBadge status={run.status} />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {jobs.find((j) => j.job === run.job)?.name ?? run.job}
                    </div>
                    <div className="text-xs break-words text-ink-soft">{summary(run)}</div>
                  </div>
                  <span
                    className="shrink-0 text-xs text-ink-faint"
                    title={formatDateTime(run.started_at)}
                  >
                    {timeAgo(run.started_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </div>
  )
}
