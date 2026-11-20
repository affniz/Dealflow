import { useQuery } from "@tanstack/react-query"

import {
  companiesListCompaniesOptions,
  usersUserDirectoryOptions,
} from "@/client/@tanstack/react-query.gen"
import type { NamedRef } from "@/client/types.gen"
import { Select } from "@/components/ui/field"
import { toId } from "@/lib/forms"

/** Who can own records: everyone active except viewers. Only admins may pick someone else. */
export function OwnerSelect({
  id,
  value,
  onChange,
}: {
  id: string
  value: number | null
  onChange: (id: number | null) => void
}) {
  const directory = useQuery(usersUserDirectoryOptions())
  return (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(toId(e.target.value))}>
      {directory.data
        ?.filter((u) => u.role !== "viewer")
        .map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
    </Select>
  )
}

/**
 * Pick a company, or none. `current` is the record's present company: an agent may not
 * otherwise see it (it can belong to a teammate), but the picker still has to show it.
 */
export function CompanySelect({
  id,
  value,
  current,
  onChange,
}: {
  id: string
  value: number | null
  current?: NamedRef | null
  onChange: (id: number | null) => void
}) {
  const companies = useQuery(companiesListCompaniesOptions({ query: { limit: 200 } }))
  const options = (companies.data?.data ?? []).map((c) => ({ id: c.id, name: c.name }))
  if (current && !options.some((o) => o.id === current.id)) options.unshift(current)
  return (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(toId(e.target.value))}>
      <option value="">None</option>
      {options.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </Select>
  )
}
