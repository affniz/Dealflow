import { useQuery } from "@tanstack/react-query"

import { usersUserDirectoryOptions } from "@/client/@tanstack/react-query.gen"
import { Select } from "@/components/ui/field"

/**
 * Whose records to list: "all", "me" or a user id. Only shown to people who see the whole
 * team; agents only ever see their own records.
 */
export function OwnerFilter({
  value,
  onChange,
  allLabel = "Everyone",
}: {
  value: string
  onChange: (value: string) => void
  allLabel?: string
}) {
  const directory = useQuery(usersUserDirectoryOptions())
  return (
    <Select
      aria-label="Owner"
      className="w-auto"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="all">{allLabel}</option>
      <option value="me">Mine</option>
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

export function SortSelect({
  value,
  onChange,
}: {
  value: "name" | "recent"
  onChange: (value: "name" | "recent") => void
}) {
  return (
    <Select
      aria-label="Sort"
      className="w-auto"
      value={value}
      onChange={(e) => onChange(e.target.value as "name" | "recent")}
    >
      <option value="name">Name A–Z</option>
      <option value="recent">Recently updated</option>
    </Select>
  )
}
