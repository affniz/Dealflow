import { afterEach, describe, expect, it, vi } from "vitest"

import { formatCount, formatUsd } from "@/lib/money"
import { fromLocalInput, startOfTomorrow, toLocalInput } from "@/lib/time"
import { formatMoney, formatMoneyShort, initials, timeAgo } from "@/lib/utils"

afterEach(() => {
  vi.useRealTimers()
})

describe("money", () => {
  it("groups rupees the Indian way and dollars the US way", () => {
    expect(formatMoney("250000.50")).toBe("₹2,50,000.5")
    expect(formatMoney(1200, "USD")).toBe("$1,200")
    expect(formatMoney(null)).toBe("₹0")
    expect(formatMoneyShort(250000)).toBe("₹2.5L")
    expect(formatMoneyShort(12_000_000)).toBe("₹1.2Cr")
  })

  it("shows small AI costs with enough decimals", () => {
    expect(formatUsd("0.0123")).toBe("$0.0123")
    expect(formatUsd(12.5)).toBe("$12.50")
    expect(formatUsd(0)).toBe("$0.00")
    expect(formatCount(1234)).toBe("1,234")
    expect(formatCount(25_000)).toBe("25K")
  })
})

describe("time", () => {
  it("says how long ago, in the largest unit that fits", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-11-24T12:00:00Z"))
    expect(timeAgo("2026-11-24T11:59:30Z")).toBe("just now")
    expect(timeAgo("2026-11-24T11:55:00Z")).toBe("5 minutes ago")
    expect(timeAgo("2026-11-23T12:00:00Z")).toBe("yesterday")
    expect(timeAgo("2026-11-26T12:00:00Z")).toBe("in 2 days")
  })

  it("round-trips a date-time input in the browser's time zone", () => {
    const iso = "2026-11-24T04:30:00.000Z"
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso)
    expect(toLocalInput(null)).toBe("")
    expect(fromLocalInput("")).toBeNull()
  })

  it("finds the start of tomorrow", () => {
    const tomorrow = startOfTomorrow(new Date(2026, 10, 24, 18, 45).getTime())
    expect(tomorrow).toEqual(new Date(2026, 10, 25, 0, 0, 0, 0))
  })
})

describe("initials", () => {
  it("come from a name or an email address", () => {
    expect(initials("Priya Shah")).toBe("PS")
    expect(initials("owner@example.com")).toBe("OE")
    expect(initials("")).toBe("")
  })
})
