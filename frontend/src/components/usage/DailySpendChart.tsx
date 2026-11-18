import { useEffect, useRef, useState } from "react"

import type { DailyUsage } from "@/client/types.gen"
import { formatUsd } from "@/lib/money"

const HEIGHT = 200
const PAD = { top: 12, right: 8, bottom: 24, left: 52 }
const MAX_BAR = 24

function niceStep(max: number) {
  // clean tick steps: 1, 2 or 5 x 10^n, about four ticks
  const raw = max / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw
}

/** One column per day of the month; a single series, so the title names it (no legend). */
export function DailySpendChart({ month, days }: { month: string; days: DailyUsage[] }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry!.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const [year, mon] = month.split("-").map(Number) as [number, number]
  const dayCount = new Date(year, mon, 0).getDate()
  const byDay = new Map(days.map((d) => [Number(d.date.slice(8, 10)), Number(d.cost_usd)]))
  const values = Array.from({ length: dayCount }, (_, i) => byDay.get(i + 1) ?? 0)

  const peak = Math.max(...values, 0)
  const step = peak > 0 ? niceStep(peak) : 0.01
  const top = Math.max(step, Math.ceil(peak / step) * step)
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)

  const plotW = Math.max(width - PAD.left - PAD.right, 100)
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const slot = plotW / dayCount
  const barW = Math.min(MAX_BAR, Math.max(slot - 2, 1)) // 2px surface gap between columns
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH
  const labelEvery = slot < 18 ? 5 : slot < 28 ? 2 : 1

  const hovered = hover !== null ? { day: hover + 1, value: values[hover]! } : null

  return (
    <div ref={wrapRef} className="relative">
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label={`Daily AI spend for ${month}`}
        className="block overflow-visible"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={PAD.left + plotW}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-chart-grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(t)}
              dy="0.32em"
              textAnchor="end"
              className="fill-ink-faint text-[11px] tabular-nums"
            >
              {formatUsd(t, { ticks: true })}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          const x = PAD.left + i * slot + (slot - barW) / 2
          const h = y(0) - y(v)
          const r = Math.min(4, h, barW / 2)
          // 4px rounded data-end, square at the baseline
          const path =
            h > 0
              ? `M${x},${y(0)} V${y(v) + r} Q${x},${y(v)} ${x + r},${y(v)} H${x + barW - r} Q${x + barW},${y(v)} ${x + barW},${y(v) + r} V${y(0)} Z`
              : ""
          return (
            <g key={i}>
              {path && (
                <path
                  d={path}
                  fill="var(--color-chart-series)"
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
              {/* the whole day slot is the hit target, not just the painted column */}
              <rect
                x={PAD.left + i * slot}
                y={PAD.top}
                width={slot}
                height={plotH}
                fill="transparent"
                tabIndex={0}
                aria-label={`${month}-${String(i + 1).padStart(2, "0")}: ${formatUsd(v)}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="outline-none"
              />
              {(i + 1) % labelEvery === 0 || i === 0 ? (
                <text
                  x={PAD.left + i * slot + slot / 2}
                  y={HEIGHT - 6}
                  textAnchor="middle"
                  className="fill-ink-faint text-[11px] tabular-nums"
                >
                  {i + 1}
                </text>
              ) : null}
            </g>
          )
        })}
        <line
          x1={PAD.left}
          x2={PAD.left + plotW}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--color-chart-axis)"
          strokeWidth={1}
        />
      </svg>
      {hovered && (
        <div
          role="status"
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs shadow-md"
          style={{
            left: Math.min(Math.max(PAD.left + (hovered.day - 0.5) * slot, 60), width - 60),
            top: Math.max(y(hovered.value) - 52, 0),
          }}
        >
          <div className="font-semibold text-ink tabular-nums">{formatUsd(hovered.value)}</div>
          <div className="text-ink-soft">
            {new Date(year, mon - 1, hovered.day).toLocaleDateString(undefined, {
              day: "numeric",
              month: "short",
            })}
          </div>
        </div>
      )}
    </div>
  )
}
