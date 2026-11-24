import { screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { SystemStatus } from "@/client/types.gen"
import { SystemSettings } from "@/components/settings/SystemSettings"
import { mockApi } from "@/test/api"
import { renderWithApp } from "@/test/render"

const run = (job: string, status: string, extra: object = {}) => ({
  id: Math.floor(Math.random() * 1e6),
  job,
  status,
  started_at: new Date(Date.now() - 3_600_000).toISOString(),
  finished_at: new Date().toISOString(),
  result: {},
  error: null,
  ...extra,
})

const status = (overrides: Partial<SystemStatus> = {}): SystemStatus =>
  ({
    problems: [],
    jobs: [
      {
        job: "pipeline_review",
        name: "Morning pipeline review",
        schedule: "Daily from 07:00 (Asia/Kolkata)",
        last_run: run("pipeline_review", "warning", { error: "1 of 4 deal reviews failed" }),
        last_success_at: null,
      },
      {
        job: "check_rotting",
        name: "Stalled-deal check",
        schedule: "Every hour",
        last_run: null,
        last_success_at: null,
      },
    ],
    recent_runs: [
      run("pipeline_review", "warning", { error: "1 of 4 deal reviews failed" }),
      run("purge_trash", "succeeded", { result: { deal: 2, job_runs: 0 } }),
    ],
    sentry: false,
    emails: true,
    ...overrides,
  }) as SystemStatus

describe("SystemSettings", () => {
  it("lists what needs attention and how each job last went", async () => {
    const problem = "Morning pipeline review had a problem on 24 Nov, 07:00 IST: 1 of 4 failed"
    mockApi({ "GET /api/v1/system/status": { json: status({ problems: [problem] }) } })
    renderWithApp(<SystemSettings />)

    const attention = await screen.findByRole("list", { name: "Needs attention" })
    expect(attention).toHaveTextContent(problem)
    const jobs = within(screen.getByRole("region", { name: "Background jobs" }))
    const review = jobs.getByText("Morning pipeline review").closest("li")!
    expect(within(review).getByText("Problem")).toBeInTheDocument()
    expect(within(review).getByText("Hasn't worked yet")).toBeInTheDocument()
    expect(jobs.getByText("Stalled-deal check").closest("li")).toHaveTextContent("Hasn't run yet")
    // what a run did, from the counts it returned
    expect(screen.getByText("deal: 2 · job runs: 0")).toBeInTheDocument()
    expect(screen.getByText(/the owner and admins get an email/)).toBeInTheDocument()
    expect(screen.getByText(/Set SENTRY_DSN/)).toBeInTheDocument()
  })

  it("says so when all is well", async () => {
    mockApi({ "GET /api/v1/system/status": { json: status({ recent_runs: [] }) } })
    renderWithApp(<SystemSettings />)
    expect(await screen.findByText("Everything is working.")).toBeInTheDocument()
    expect(screen.getByText(/No jobs have run yet/)).toBeInTheDocument()
  })
})
