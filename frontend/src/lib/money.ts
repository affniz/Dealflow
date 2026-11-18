/** US dollars, which is what the Claude API bills in. Small amounts keep enough decimals. */
export function formatUsd(value: string | number | null | undefined, opts?: { ticks?: boolean }) {
  const n = Number(value ?? 0)
  const digits = opts?.ticks
    ? n !== 0 && Math.abs(n) < 1
      ? 2
      : 0
    : n !== 0 && Math.abs(n) < 1
      ? 4
      : 2
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    // amounts under $1 always show 4 decimals so a column of them lines up
    minimumFractionDigits: opts?.ticks ? (n === 0 ? 0 : Math.min(digits, 2)) : digits,
    maximumFractionDigits: digits,
  }).format(n)
}

export function formatCount(n: number) {
  return new Intl.NumberFormat("en-US", { notation: n >= 10_000 ? "compact" : "standard" }).format(
    n,
  )
}
