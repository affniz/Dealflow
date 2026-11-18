import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, CircleAlert } from "lucide-react"
import { type ReactNode, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"

import { usageUsageSummaryOptions } from "@/client/@tanstack/react-query.gen"
import type { UsageSummary } from "@/client/types.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { DailySpendChart } from "@/components/usage/DailySpendChart"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { formatCount, formatUsd } from "@/lib/money"
import { cn } from "@/lib/utils"

const FEATURE_NAMES: Record<string, { name: string; unit: string }> = {
  copilot: { name: "Copilot", unit: "questions" },
  pipeline_agent: { name: "Pipeline agent", unit: "deal reviews" },
}

function shiftMonth(month: string, by: number) {
  const [y, m] = month.split("-").map(Number) as [number, number]
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

/** What the AI features cost, for admins. Amounts are USD, as Anthropic bills them. */
export function UsagePage() {
  const [params, setParams] = useSearchParams()
  const month = params.get("month") ?? undefined
  const summary = useQuery({
    ...usageUsageSummaryOptions({ query: { month } }),
    placeholderData: (prev) => prev, // keep the frame while the next month loads
  })
  const data = summary.data
  const current = data?.month

  return (
    <>
      <PageHeader title="AI usage" />
      {/* filters: one row, above everything they scope */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-4 md:px-6">
        <Button
          variant="outline"
          size="icon"
          aria-label="Previous month"
          disabled={!current}
          onClick={() => setParams({ month: shiftMonth(current!, -1) })}
        >
          <ChevronLeft />
        </Button>
        <span className="min-w-32 text-center text-sm font-medium" aria-live="polite">
          {current
            ? new Date(`${current}-01T00:00:00`).toLocaleDateString(undefined, {
                month: "long",
                year: "numeric",
              })
            : "…"}
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Next month"
          disabled={!current || !month}
          onClick={() => {
            const next = shiftMonth(current!, 1)
            setParams(next >= new Date().toISOString().slice(0, 7) ? {} : { month: next })
          }}
        >
          <ChevronRight />
        </Button>
        {data && (
          <span className="text-xs text-ink-faint">
            Prices as of {data.prices_as_of}; days in the team's time zone.
          </span>
        )}
      </div>

      {summary.isPending ? (
        <div className="grid place-items-center py-16">
          <Spinner />
        </div>
      ) : summary.isError ? (
        <p className="px-6 text-sm text-red-600">Couldn't load usage.</p>
      ) : (
        <div
          className={cn(
            "space-y-6 px-4 pb-8 transition-opacity md:px-6",
            summary.isFetching && "opacity-60",
          )}
        >
          <Tiles data={data!} />
          <BudgetLine data={data!} />
          <DailyCard data={data!} />
          <div className="grid gap-6 lg:grid-cols-2">
            <ByFeature data={data!} />
            <ByPerson data={data!} />
          </div>
          <ByModel data={data!} />
        </div>
      )}
    </>
  )
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-ink-soft">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-1 text-xs text-ink-faint">{note}</p>}
    </Card>
  )
}

function Tiles({ data }: { data: UsageSummary }) {
  const feature = (f: string) => data.by_feature.find((x) => x.feature === f)
  const copilot = feature("copilot")
  const pipeline = feature("pipeline_agent")
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile label="Spend this month" value={formatUsd(data.total.cost_usd)} />
      <Tile
        label="Per Copilot question"
        value={copilot?.avg_cost_per_unit ? formatUsd(copilot.avg_cost_per_unit) : "–"}
        note={copilot ? `${formatCount(copilot.units)} questions` : "No questions yet"}
      />
      <Tile
        label="Per deal review"
        value={pipeline?.avg_cost_per_unit ? formatUsd(pipeline.avg_cost_per_unit) : "–"}
        note={pipeline ? `${formatCount(pipeline.units)} reviews` : "No reviews yet"}
      />
      <Tile
        label="Model calls"
        value={formatCount(data.total.calls)}
        note={
          data.unpriced_calls
            ? `${data.unpriced_calls} with no price on file, not in the totals`
            : `${formatCount(data.total.input_tokens + data.total.cache_read_tokens + data.total.cache_write_tokens)} input · ${formatCount(data.total.output_tokens)} output tokens`
        }
      />
    </div>
  )
}

function DailyCard({ data }: { data: UsageSummary }) {
  const [asTable, setAsTable] = useState(false)
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Spend per day</h2>
        <Button
          variant="ghost"
          size="sm"
          aria-pressed={asTable}
          onClick={() => setAsTable(!asTable)}
        >
          {asTable ? "Show chart" : "Show table"}
        </Button>
      </div>
      {asTable ? (
        <Table
          head={["Day", "Spend"]}
          rows={data.daily.map((d) => [
            new Date(`${d.date}T00:00:00`).toLocaleDateString(undefined, {
              day: "numeric",
              month: "short",
            }),
            formatUsd(d.cost_usd),
          ])}
          empty="No AI usage this month."
        />
      ) : data.total.calls === 0 ? (
        <p className="py-10 text-center text-sm text-ink-faint">No AI usage this month.</p>
      ) : (
        <DailySpendChart month={data.month} days={data.daily} />
      )}
    </Card>
  )
}

function ByFeature({ data }: { data: UsageSummary }) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold">By feature</h2>
      <Table
        head={["Feature", "Spend", "Used", "Average"]}
        rows={data.by_feature.map((f) => {
          const meta = FEATURE_NAMES[f.feature] ?? { name: f.feature, unit: "runs" }
          return [
            meta.name,
            formatUsd(f.cost_usd),
            `${formatCount(f.units)} ${meta.unit}`,
            f.avg_cost_per_unit ? formatUsd(f.avg_cost_per_unit) : "–",
          ]
        })}
        empty="Nothing yet."
      />
    </Card>
  )
}

function ByPerson({ data }: { data: UsageSummary }) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold">By person</h2>
      <Table
        head={["Person", "Copilot", "Of budget", "Questions", "Pipeline agent"]}
        rows={data.by_user.map((u) => [
          u.user?.name ?? "Deleted user",
          formatUsd(u.copilot_cost_usd),
          pctOf(u.copilot_cost_usd, data.copilot_budget_per_person_usd),
          formatCount(u.copilot_questions),
          formatUsd(u.pipeline_cost_usd),
        ])}
        empty="Nothing yet."
      />
      <p className="mt-2 text-xs text-ink-faint">
        Pipeline agent costs are listed under the deal's owner it worked for.
      </p>
    </Card>
  )
}

function pctOf(spent: string | number, budget: string | number | null | undefined) {
  if (budget == null) return "–"
  const b = Number(budget)
  return b > 0 ? `${Math.floor((Number(spent) * 100) / b)}%` : "100%"
}

/** Budgets apply to the current month only, so this shows nothing for past months. */
function BudgetLine({ data }: { data: UsageSummary }) {
  const p = data.pipeline_budget
  if (!p && data.copilot_budget_per_person_usd == null) return null
  const high = (p?.used_pct ?? 0) >= 80
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
      {p && (
        <span
          className={cn("flex items-center gap-1", high && "text-amber-700 dark:text-amber-400")}
        >
          {high && <CircleAlert className="size-4" aria-hidden />}
          Pipeline agent budget:{" "}
          {p.budget_usd == null
            ? `${formatUsd(p.spent_usd)} spent, no limit`
            : `${formatUsd(p.spent_usd)} of ${formatUsd(p.budget_usd)} (${p.used_pct}%)`}
        </span>
      )}
      <span>
        Copilot limit:{" "}
        {data.copilot_budget_per_person_usd == null
          ? "none"
          : `${formatUsd(data.copilot_budget_per_person_usd)} per person`}
      </span>
      <Link to="/settings" className="text-brand-700 hover:underline">
        Change budgets
      </Link>
    </p>
  )
}

function ByModel({ data }: { data: UsageSummary }) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold">By model</h2>
      <Table
        head={["Model", "Spend", "Calls", "Input", "Cache reads", "Cache writes", "Output"]}
        rows={data.by_model.map((m) => [
          m.model,
          formatUsd(m.cost_usd),
          formatCount(m.calls),
          formatCount(m.input_tokens),
          formatCount(m.cache_read_tokens),
          formatCount(m.cache_write_tokens),
          formatCount(m.output_tokens),
        ])}
        empty="Nothing yet."
      />
    </Card>
  )
}

function Table({ head, rows, empty }: { head: string[]; rows: ReactNode[][]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-ink-faint">{empty}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-soft">
            {head.map((h, i) => (
              <th key={h} className={cn("py-2 pr-3 font-medium", i > 0 && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-line last:border-0">
              {row.map((cell, i) => (
                <td key={i} className={cn("py-2 pr-3", i > 0 && "text-right tabular-nums")}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
