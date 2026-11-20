/** Helpers shared by the record forms and list filters. */

export const toId = (v: string) => (v ? Number(v) : null)

/** JSON with object keys sorted, so equal objects compare equal whatever their key order. */
function stableJson(value: unknown): string {
  return JSON.stringify(value, (_, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)))
      : v,
  )
}

/** Equal values, comparing objects by content. */
export function same(a: unknown, b: unknown) {
  return a && b && typeof a === "object" && typeof b === "object"
    ? stableJson(a) === stableJson(b)
    : a === b
}

/** The fields of `next` that differ from `current`, for a PATCH that only sends changes. */
export function changedFields<T extends Record<string, unknown>>(
  next: T,
  current: Record<string, unknown>,
): Partial<T> {
  return Object.fromEntries(
    Object.entries(next).filter(([k, v]) => !same(v, current[k] ?? null)),
  ) as Partial<T>
}

// ---------------------------------------------------------------- custom fields

/** One custom field being edited. `original` keeps a non-text value (a number, true/false) as it
 * was unless the text is changed. */
export type FieldRow = { id: number; name: string; text: string; original?: unknown }

let nextRowId = 1
export const newFieldRow = (): FieldRow => ({ id: nextRowId++, name: "", text: "" })

export function toFieldRows(fields: Record<string, unknown> | null | undefined): FieldRow[] {
  return Object.entries(fields ?? {}).map(([name, value]) => ({
    id: nextRowId++,
    name,
    text: value === null || value === undefined ? "" : String(value),
    original: value,
  }))
}

/** The rows as a custom_fields object, and a message saying what to fix if they aren't valid. */
export function fromFieldRows(rows: FieldRow[]): {
  fields: Record<string, unknown>
  error: string | null
} {
  const fields: Record<string, unknown> = {}
  for (const row of rows) {
    const name = row.name.trim()
    const text = row.text.trim()
    if (!name && !text) continue // an empty row: ignore it
    if (!name) return { fields, error: `Give the custom field with “${text}” a name.` }
    if (name in fields) return { fields, error: `There are two custom fields called “${name}”.` }
    const unchanged = row.original !== undefined && text === String(row.original ?? "")
    fields[name] = unchanged ? row.original : text
  }
  return { fields, error: null }
}

/** "" -> null, so cleared optional fields are saved as empty rather than as "". */
export const orNull = (v: string) => v.trim() || null

/** The owner_id query parameter for an OwnerFilter value. */
export function ownerQuery(value: string, me: number | undefined) {
  if (value === "me") return me
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : undefined
}
