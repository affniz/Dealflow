import { Plus, X } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { type FieldRow, newFieldRow } from "@/lib/forms"

/** Edit a record's custom fields as name/value pairs (e.g. City: Pune, GSTIN: 27AAACT…). */
export function CustomFieldsEditor({
  rows,
  onChange,
}: {
  rows: FieldRow[]
  onChange: (rows: FieldRow[]) => void
}) {
  const [added, setAdded] = useState<number | null>(null)
  const update = (id: number, patch: Partial<FieldRow>) =>
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)))

  return (
    <fieldset className="space-y-2 border-t border-line pt-4">
      <legend className="sr-only">Custom fields</legend>
      <p className="text-xs font-medium tracking-wide text-ink-faint uppercase">Custom fields</p>
      {rows.map((row, i) => (
        <div key={row.id} className="flex items-center gap-2">
          <Input
            aria-label={`Custom field ${i + 1} name`}
            placeholder="Name, e.g. City"
            maxLength={50}
            autoFocus={row.id === added}
            value={row.name}
            onChange={(e) => update(row.id, { name: e.target.value })}
            className="w-2/5"
          />
          <Input
            aria-label={`Custom field ${i + 1} value`}
            placeholder="Value"
            maxLength={500}
            value={row.text}
            onChange={(e) => update(row.id, { text: e.target.value })}
            className="flex-1"
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove custom field ${row.name || i + 1}`}
            onClick={() => onChange(rows.filter((r) => r.id !== row.id))}
          >
            <X />
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          const row = newFieldRow()
          setAdded(row.id) // type straight into the new row
          onChange([...rows, row])
        }}
      >
        <Plus /> Add field
      </Button>
    </fieldset>
  )
}
