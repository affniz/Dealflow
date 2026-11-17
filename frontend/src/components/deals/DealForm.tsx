import { useQuery } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"

import {
  companiesListCompaniesOptions,
  contactsListContactsOptions,
  usersUserDirectoryOptions,
} from "@/client/@tanstack/react-query.gen"
import type { NamedRef, StagePublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { DialogFooter } from "@/components/ui/dialog"
import { Field, Select } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

export type DealFormValues = {
  title: string
  value: string
  stage_id: number | null
  company_id: number | null
  contact_id: number | null
  owner_id: number | null
  expected_close_date: string | null
}

const toId = (v: string) => (v ? Number(v) : null)

/**
 * Shared by "New deal" and "Edit deal". Stage is only shown when `stages` is passed.
 * `linked` is the deal's current company and contact: an agent may not otherwise see them (they
 * can belong to a teammate), but the form still has to show them.
 */
export function DealForm({
  initial,
  linked,
  stages,
  canAssign,
  busy,
  error,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: DealFormValues
  linked?: { company?: NamedRef | null; contact?: NamedRef | null }
  stages?: StagePublic[]
  canAssign: boolean
  busy: boolean
  error: string | null
  submitLabel: string
  onSubmit: (values: DealFormValues) => void
  onCancel: () => void
}) {
  const [v, setV] = useState(initial)
  const companies = useQuery(companiesListCompaniesOptions({ query: { limit: 200 } }))
  const contacts = useQuery(contactsListContactsOptions({ query: { limit: 200 } }))
  const directory = useQuery({ ...usersUserDirectoryOptions(), enabled: canAssign })

  const visibleContacts =
    contacts.data?.data.filter((c) => !v.company_id || c.company_id === v.company_id) ?? []
  const companyOptions = (companies.data?.data ?? []).map((c) => ({ id: c.id, name: c.name }))
  const contactOptions = visibleContacts.map((c) => ({
    id: c.id,
    name: [c.first_name, c.last_name].filter(Boolean).join(" "),
  }))
  for (const [ref, options] of [
    [linked?.company, companyOptions],
    [linked?.contact, contactOptions],
  ] as const) {
    if (ref && !options.some((o) => o.id === ref.id)) options.unshift(ref)
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    onSubmit(v)
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Title" htmlFor="deal-title">
        <Input
          id="deal-title"
          required
          maxLength={255}
          value={v.title}
          onChange={(e) => setV({ ...v, title: e.target.value })}
          placeholder="e.g. Annual licence"
          autoFocus
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Value (₹)" htmlFor="deal-value">
          <Input
            id="deal-value"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={v.value}
            onChange={(e) => setV({ ...v, value: e.target.value })}
          />
        </Field>
        <Field label="Expected close" htmlFor="deal-close">
          <Input
            id="deal-close"
            type="date"
            value={v.expected_close_date ?? ""}
            onChange={(e) => setV({ ...v, expected_close_date: e.target.value || null })}
          />
        </Field>
      </div>
      {stages && (
        <Field label="Stage" htmlFor="deal-stage">
          <Select
            id="deal-stage"
            value={v.stage_id ?? ""}
            onChange={(e) => setV({ ...v, stage_id: toId(e.target.value) })}
          >
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.probability}%)
              </option>
            ))}
          </Select>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Company" htmlFor="deal-company">
          <Select
            id="deal-company"
            value={v.company_id ?? ""}
            onChange={(e) => {
              const company_id = toId(e.target.value)
              const contact = contacts.data?.data.find((c) => c.id === v.contact_id)
              const keepContact = !company_id || contact?.company_id === company_id
              setV({ ...v, company_id, contact_id: keepContact ? v.contact_id : null })
            }}
          >
            <option value="">None</option>
            {companyOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Contact" htmlFor="deal-contact">
          <Select
            id="deal-contact"
            value={v.contact_id ?? ""}
            onChange={(e) => {
              const contact_id = toId(e.target.value)
              const contact = contacts.data?.data.find((c) => c.id === contact_id)
              setV({ ...v, contact_id, company_id: v.company_id ?? contact?.company_id ?? null })
            }}
          >
            <option value="">None</option>
            {contactOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {canAssign && (
        <Field label="Owner" htmlFor="deal-owner">
          <Select
            id="deal-owner"
            value={v.owner_id ?? ""}
            onChange={(e) => setV({ ...v, owner_id: toId(e.target.value) })}
          >
            {directory.data
              ?.filter((u) => u.role !== "viewer")
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </Select>
        </Field>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : submitLabel}
        </Button>
      </DialogFooter>
    </form>
  )
}
