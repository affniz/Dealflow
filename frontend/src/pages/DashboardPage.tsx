import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Flame } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import {
  dashboardLostReasonsOptions,
  dashboardPipelineSummaryOptions,
  dealsListDealsOptions,
  pipelinesListPipelinesOptions,
} from "@/client/@tanstack/react-query.gen"
import type { DealPublic, LostReasonReport, PipelineSummary } from "@/client/types.gen"
import { HBarChart } from "@/components/dashboard/HBarChart"
import { PageHeader } from "@/components/layout/AppLayout"
import { OwnerFilter } from "@/components/records/filters"
import { Card, Spinner } from "@/components/ui/card"
import { Select } from "@/components/ui/field"
import { permissions, useAuth } from "@/lib/auth"
import { ownerQuery } from "@/lib/forms"
import { useListParams } from "@/lib/listParams"
import { cn, formatMoney, formatMoneyShort, timeAgo } from "@/lib/utils"

const PERIODS = [
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 12 months" },
  { value: "all", label: "All time" },
]

const pct = (share: number) => `${Math.round(share * 100)}%`
const deals = (n: number) => `${n} ${n === 1 ? "deal" : "deals"}`

/** The team's (or one person's) pipeline at a glance: what's open, what closed, why deals were lost. */
export function DashboardPage() {
  const { user } = useAuth()
  const { seesTeam } = permissions(user)
  const { params, set } = useListParams()
  const pipelines = useQuery(pipelinesListPipelinesOptions())
  const pipelineId = Number(params.get("pipeline")) || pipelines.data?.[0]?.id
  const period = PERIODS.some((p) => p.value === params.get("period"))
    ? params.get("period")!
    : "90"
  const days = period === "all" ? undefined : Number(period)
  const owner = seesTeam ? (params.get("owner") ?? "all") : "all"
  const owner_id = ownerQuery(owner, user?.id)
  const periodLabel = PERIODS.find((p) => p.value === period)!.label.toLowerCase()

  const summary = useQuery({
    ...dashboardPipelineSummaryOptions({
      path: { pipeline_id: pipelineId ?? 0 },
      query: { days, owner_id },
    }),
    enabled: pipelineId !== undefined,
    placeholderData: keepPreviousData,
  })
  const lost = useQuery({
    ...dashboardLostReasonsOptions({
      // the lost-reason report needs a window; "all time" means ten years
      query: { pipeline_id: pipelineId, days: days ?? 3650, owner_id },
    }),
    enabled: pipelineId !== undefined,
    placeholderData: keepPreviousData,
  })
  const stalled = useQuery({
    ...dealsListDealsOptions({
      query: { pipeline_id: pipelineId, status: "open", rotting: true, owner_id, limit: 8 },
    }),
    enabled: pipelineId !== undefined,
  })

  return (
    <>
      <PageHeader title="Dashboard" />
      <div className="space-y-5 px-4 pb-8 md:px-6">
        {/* filters: one row, above everything they scope */}
        <div className="flex flex-wrap items-center gap-2">
          {pipelines.data && pipelines.data.length > 1 && (
            <Select
              aria-label="Pipeline"
              className="w-auto"
              value={pipelineId}
              onChange={(e) => set({ pipeline: e.target.value })}
            >
              {pipelines.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
          <Select
            aria-label="Period"
            className="w-auto"
            value={period}
            onChange={(e) => set({ period: e.target.value === "90" ? null : e.target.value })}
          >
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
          {seesTeam && (
            <OwnerFilter
              value={owner}
              allLabel="Whole team"
              onChange={(v) => set({ owner: v === "all" ? null : v })}
            />
          )}
        </div>

        {summary.isPending || pipelines.isPending ? (
          <div className="grid place-items-center p-12">
            <Spinner />
          </div>
        ) : summary.isError ? (
          <Card className="p-6 text-sm text-ink-soft">Couldn't load the dashboard.</Card>
        ) : (
          <div className={cn("space-y-5", summary.isPlaceholderData && "opacity-60")}>
            <Kpis s={summary.data} periodLabel={periodLabel} />
            <div className="grid gap-5 lg:grid-cols-2">
              <ChartCard
                title="Open pipeline by stage"
                subtitle="Value of open deals in each stage; hover for the weighted forecast."
              >
                <StageChart s={summary.data} />
              </ChartCard>
              <ChartCard
                title="Why deals were lost"
                subtitle={`Deals lost ${periodLabel}, most common reason first.`}
              >
                {lost.isPending ? <Spinner /> : lost.data && <LostChart r={lost.data} />}
              </ChartCard>
            </div>
            <StalledCard
              count={summary.data.rotting_count ?? 0}
              rows={stalled.data?.data ?? []}
              pipelineId={pipelineId}
            />
          </div>
        )}
      </div>
    </>
  )
}

function Kpis({ s, periodLabel }: { s: PipelineSummary; periodLabel: string }) {
  const closed = s.won_count + s.lost_count
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile
        label="Open pipeline"
        value={formatMoneyShort(s.open_value)}
        title={formatMoney(s.open_value)}
        note={deals(s.open_count)}
      />
      <StatTile
        label="Weighted forecast"
        value={formatMoneyShort(s.weighted_value)}
        title={formatMoney(s.weighted_value)}
        note="Weighted by stage win chance"
      />
      <StatTile
        label="Won"
        value={formatMoneyShort(s.won_value)}
        title={formatMoney(s.won_value)}
        note={`${deals(s.won_count)}, ${periodLabel}`}
      />
      <StatTile
        label="Win rate"
        value={s.win_rate == null ? "—" : pct(s.win_rate)}
        note={
          closed === 0 ? `No deals closed ${periodLabel}` : `${s.won_count} won of ${closed} closed`
        }
      />
    </dl>
  )
}

function StatTile({
  label,
  value,
  note,
  title,
}: {
  label: string
  value: string
  note: string
  title?: string
}) {
  return (
    <Card className="px-4 py-3">
      <dt className="text-xs font-medium text-ink-soft">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums" title={title}>
        {value}
      </dd>
      <dd className="mt-0.5 truncate text-xs text-ink-faint">{note}</dd>
    </Card>
  )
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mt-0.5 mb-4 text-xs text-ink-soft">{subtitle}</p>
      {children}
    </Card>
  )
}

function StageChart({ s }: { s: PipelineSummary }) {
  if (s.open_count === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">No open deals.</p>
  }
  // stages keep their pipeline order: it's the order deals move through
  return (
    <HBarChart
      label="Open pipeline value by stage"
      rows={s.stages.map((st) => ({
        key: st.stage_id,
        label: st.name,
        value: Number(st.total_value),
        valueLabel: st.deal_count ? `${formatMoneyShort(st.total_value)} · ${st.deal_count}` : "—",
        description: `${st.name}: ${deals(st.deal_count)}, ${formatMoney(st.total_value)}, weighted ${formatMoney(st.weighted_value)}`,
        detail: (
          <>
            <div className="font-semibold text-ink">{st.name}</div>
            <div className="text-ink-soft">
              {deals(st.deal_count)} · {formatMoney(st.total_value)}
            </div>
            <div className="text-ink-soft">
              Weighted ({st.probability}%): {formatMoney(st.weighted_value)}
            </div>
          </>
        ),
      }))}
      table={{
        headers: ["Stage", "Deals", "Value", "Win chance", "Weighted"],
        rows: s.stages.map((st) => [
          st.name,
          st.deal_count,
          formatMoney(st.total_value),
          `${st.probability}%`,
          formatMoney(st.weighted_value),
        ]),
      }}
    />
  )
}

function LostChart({ r }: { r: LostReasonReport }) {
  if (r.lost_count === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">No lost deals in this period.</p>
  }
  return (
    <>
      <HBarChart
        label="Lost deals by reason"
        rows={r.reasons.map((x) => ({
          key: x.reason_id,
          label: x.label,
          value: x.count,
          valueLabel: `${x.count} · ${pct(x.share)}`,
          description: `${x.label}: ${deals(x.count)}, ${pct(x.share)} of lost deals, ${formatMoney(x.value)}`,
          detail: (
            <>
              <div className="font-semibold text-ink">{x.label}</div>
              <div className="text-ink-soft">
                {deals(x.count)} · {pct(x.share)} of lost deals
              </div>
              <div className="text-ink-soft">Value lost: {formatMoney(x.value)}</div>
            </>
          ),
        }))}
        table={{
          headers: ["Reason", "Deals", "Share", "Value"],
          rows: r.reasons.map((x) => [x.label, x.count, pct(x.share), formatMoney(x.value)]),
        }}
      />
      <p className="mt-3 text-xs text-ink-soft">
        {deals(r.lost_count)} lost, worth {formatMoney(r.lost_value)}.
      </p>
    </>
  )
}

function StalledCard({
  count,
  rows,
  pipelineId,
}: {
  count: number
  rows: DealPublic[]
  pipelineId: number | undefined
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Flame className="size-4 text-red-600" aria-hidden />
          Stalled deals
          <span className="font-normal text-ink-faint">· {count}</span>
        </h2>
        {count > 0 && (
          <Link
            to={`/?${new URLSearchParams({ ...(pipelineId ? { pipeline: String(pipelineId) } : {}), stalled: "1" })}`}
            className="text-xs text-brand-700 hover:underline"
          >
            Show on the board
          </Link>
        )}
      </div>
      {count === 0 ? (
        <p className="mt-2 text-sm text-ink-faint">
          Nothing stalled. Every open deal moved recently.
        </p>
      ) : (
        <ul className="-mx-2 mt-2 divide-y divide-line">
          {rows.map((d) => (
            <li key={d.id}>
              <Link
                to={`/deals/${d.id}`}
                className="flex items-center justify-between gap-3 rounded-md px-2 py-2 hover:bg-muted"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{d.title}</p>
                  <p className="text-xs text-ink-soft">
                    {d.owner?.name} · in this stage since {timeAgo(d.stage_changed_at)}
                  </p>
                </div>
                <span className="shrink-0 text-sm tabular-nums">
                  {formatMoney(d.value, d.currency ?? "INR")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
