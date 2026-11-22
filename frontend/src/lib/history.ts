import { formatMoney } from "@/lib/utils"

/** How changed fields are named in history lines. */
export const FIELD_LABELS: Record<string, string> = {
  first_name: "first name",
  last_name: "last name",
  job_title: "job title",
  expected_close_date: "expected close date",
  contact_id: "contact",
  company_id: "company",
  owner_id: "owner",
  custom_fields: "custom fields",
}

export function fieldLabel(field: string) {
  return FIELD_LABELS[field] ?? field.replaceAll("_", " ")
}

/** Links and custom fields are summed up by name only; their raw values aren't readable. */
const NAME_ONLY = (field: string) => field.endsWith("_id") || field === "custom_fields"

function show(field: string, value: unknown) {
  if (field === "value") return formatMoney(value as number)
  const text = String(value)
  return text.length > 60 ? `${text.slice(0, 57)}…` : text
}

/** "email from a@x.in to b@x.in", "set phone to …", "cleared industry", "changed owner". */
export function describeChange(field: string, [before, after]: unknown[]) {
  const label = fieldLabel(field)
  if (NAME_ONLY(field)) return `changed ${label}`
  const empty = (v: unknown) => v === null || v === undefined || v === ""
  if (empty(before)) return `set ${label} to “${show(field, after)}”`
  if (empty(after)) return `cleared ${label}`
  return `changed ${label} from “${show(field, before)}” to “${show(field, after)}”`
}

export function changeLines(changes: unknown): string[] {
  if (!changes || typeof changes !== "object") return []
  return Object.entries(changes as Record<string, unknown[]>).map(([f, pair]) =>
    describeChange(f, pair),
  )
}
