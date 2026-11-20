import { type ReactNode, useState } from "react"

import { cn } from "@/lib/utils"

export type BarRow = {
  key: string | number
  label: string
  value: number
  /** Printed at the bar's tip, e.g. "₹12L · 3". */
  valueLabel: string
  /** Shown on hover and keyboard focus. */
  detail: ReactNode
  /** Accessible name for the row, e.g. "Proposal: 3 deals, ₹12,00,000". */
  description: string
}

/**
 * One series of horizontal bars, in the order given, one hue. Every bar has its value at the
 * tip, so there's no value axis; the chart's title names the series, so there's no legend.
 * Below the chart, the same numbers as a table.
 */
export function HBarChart({
  rows,
  label,
  table,
}: {
  rows: BarRow[]
  /** What the chart shows, for screen readers. */
  label: string
  /** The table view: column headers and one row of cells per bar. */
  table: { headers: string[]; rows: (string | number)[][] }
}) {
  const [active, setActive] = useState<string | number | null>(null)
  const peak = Math.max(...rows.map((r) => r.value), 0)

  return (
    <div>
      <ul role="list" aria-label={label} className="space-y-1">
        {rows.map((r) => {
          const pct = peak > 0 ? (r.value / peak) * 100 : 0
          const on = active === r.key
          return (
            <li
              key={r.key}
              tabIndex={0}
              aria-label={r.description}
              onPointerEnter={() => setActive(r.key)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(r.key)}
              onBlur={() => setActive(null)}
              // the whole row is the hit target, not just the painted bar
              className="relative grid grid-cols-[minmax(5rem,9rem)_1fr] items-center gap-3 rounded-md py-1 outline-none focus-visible:ring-2 focus-visible:ring-brand-600/40"
            >
              <span className="truncate text-sm text-ink-soft" title={r.label}>
                {r.label}
              </span>
              {/* the padding keeps room for the longest bar's label; inside it, every bar is
                  the same fraction of the track as its value is of the largest */}
              <div className="min-w-0 pr-28">
                <div className="relative flex h-5 items-center">
                  {r.value > 0 && (
                    <span
                      aria-hidden
                      // thin bar, square at the baseline, 4px rounded data-end
                      className={cn(
                        "block h-4 rounded-r-[4px] bg-chart-series transition-opacity",
                        active !== null && !on && "opacity-55",
                      )}
                      style={{ width: `max(${pct}%, 2px)` }}
                    />
                  )}
                  <span
                    className="absolute text-xs font-medium whitespace-nowrap text-ink tabular-nums"
                    style={{ left: `calc(${pct}% + 0.5rem)` }}
                  >
                    {r.valueLabel}
                  </span>
                </div>
              </div>
              {on && (
                <div
                  role="status"
                  className="pointer-events-none absolute top-full right-0 z-10 mt-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs shadow-md"
                >
                  {r.detail}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-xs text-ink-faint hover:text-ink">
          View as table
        </summary>
        <table className="mt-2 w-full text-left text-xs">
          <thead className="text-ink-soft">
            <tr>
              {table.headers.map((h, i) => (
                <th key={h} className={cn("py-1 font-medium", i > 0 && "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {table.rows.map((cells, r) => (
              <tr key={r}>
                {cells.map((c, i) => (
                  <td key={i} className={cn("py-1", i > 0 && "text-right tabular-nums")}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}
