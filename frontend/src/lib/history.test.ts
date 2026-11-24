import { describe, expect, it } from "vitest"

import { changeLines, describeChange } from "@/lib/history"

describe("history lines", () => {
  it("say what changed in words", () => {
    expect(describeChange("email", ["p@zenith.in", "priya@zenith.in"])).toBe(
      "changed email from “p@zenith.in” to “priya@zenith.in”",
    )
    expect(describeChange("job_title", [null, "CFO"])).toBe("set job title to “CFO”")
    expect(describeChange("industry", ["Retail", ""])).toBe("cleared industry")
  })

  it("show money as money and links by name only", () => {
    expect(describeChange("value", [1000, 250000])).toBe(
      "changed value from “₹1,000” to “₹2,50,000”",
    )
    expect(describeChange("company_id", [null, 4])).toBe("changed company")
    expect(describeChange("custom_fields", [{}, { a: 1 }])).toBe("changed custom fields")
  })

  it("shorten long values", () => {
    const line = describeChange("notes", ["", "x".repeat(100)])
    expect(line).toBe(`set notes to “${"x".repeat(57)}…”`)
  })

  it("read a change record, and ignore anything else", () => {
    expect(changeLines({ phone: [null, "98200"], title: ["A", "B"] })).toEqual([
      "set phone to “98200”",
      "changed title from “A” to “B”",
    ])
    expect(changeLines(undefined)).toEqual([])
  })
})
