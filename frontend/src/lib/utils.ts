import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const moneyFormatters = new Map<string, Intl.NumberFormat>()

/** "250000.50" -> "₹2,50,000.50" (Indian digit grouping for INR). */
export function formatMoney(value: string | number | null | undefined, currency = "INR") {
  const key = currency
  let fmt = moneyFormatters.get(key)
  if (!fmt) {
    fmt = new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: 0,
    })
    moneyFormatters.set(key, fmt)
  }
  return fmt.format(Number(value ?? 0))
}

/** Short money for column headers: ₹2.5L, ₹1.2Cr (INR) or $12K. */
export function formatMoneyShort(value: string | number | null | undefined, currency = "INR") {
  const n = Number(value ?? 0)
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n)
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

export function timeAgo(iso: string) {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit)
  }
  return "just now"
}

export function initials(name: string) {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("")
}
