import { describe, expect, it } from "vitest"

import { changedFields, fromFieldRows, ownerQuery, same, toFieldRows } from "@/lib/forms"

describe("changedFields", () => {
  it("sends only what changed, comparing objects by content", () => {
    const current = { title: "Pilot", value: "1000", custom_fields: { a: 1, b: 2 }, owner_id: null }
    const next = { title: "Pilot", value: "2500", custom_fields: { b: 2, a: 1 }, owner_id: null }
    expect(changedFields(next, current)).toEqual({ value: "2500" })
  })

  it("treats a missing current value as empty", () => {
    expect(changedFields({ phone: null, email: "a@x.in" }, {})).toEqual({ email: "a@x.in" })
  })

  it("compares plain values strictly", () => {
    expect(same(0, null)).toBe(false)
    expect(same([1, 2], [1, 2])).toBe(true)
  })
})

describe("custom field rows", () => {
  it("keep a number or yes/no as it was unless its text was changed", () => {
    const rows = toFieldRows({ seats: 40, renewal: true, city: "Pune" })
    rows[2]!.text = "Mumbai"
    expect(fromFieldRows(rows)).toEqual({
      fields: { seats: 40, renewal: true, city: "Mumbai" },
      error: null,
    })
    rows[0]!.text = "45"
    expect(fromFieldRows(rows).fields.seats).toBe("45")
  })

  it("skip empty rows and say what to fix", () => {
    const blank = { id: 1, name: " ", text: "" }
    expect(fromFieldRows([blank]).fields).toEqual({})
    expect(fromFieldRows([{ id: 2, name: "", text: "27AAACT" }]).error).toBe(
      "Give the custom field with “27AAACT” a name.",
    )
    const twice = [
      { id: 3, name: "City", text: "Pune" },
      { id: 4, name: "City ", text: "Goa" },
    ]
    expect(fromFieldRows(twice).error).toBe("There are two custom fields called “City”.")
  })
})

describe("ownerQuery", () => {
  it("turns the owner filter into an id", () => {
    expect(ownerQuery("me", 7)).toBe(7)
    expect(ownerQuery("12", 7)).toBe(12)
    expect(ownerQuery("", 7)).toBeUndefined()
    expect(ownerQuery("all", 7)).toBeUndefined()
  })
})
