import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"

import {
  companiesCreateCompanyMutation,
  companiesUpdateCompanyMutation,
} from "@/client/@tanstack/react-query.gen"
import type { CompanyPublic } from "@/client/types.gen"
import { OwnerSelect } from "@/components/records/fields"
import { changedFields, type FieldRow, fromFieldRows, orNull, toFieldRows } from "@/lib/forms"
import { CustomFieldsEditor } from "@/components/records/CustomFieldsEditor"
import { Button } from "@/components/ui/button"
import { Field } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Sheet, SheetFooter } from "@/components/ui/sheet"
import { RECORD_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { useUnsavedChanges } from "@/lib/sheet"
import { useToast } from "@/lib/toast"

type Values = {
  name: string
  domain: string
  industry: string
  phone: string
  owner_id: number | null
  fields: FieldRow[]
}

/** "https://www.acme.in/about" -> "acme.in": store the bare domain. */
function cleanDomain(value: string) {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("/")[0] || null
  )
}

/** Add a company, or edit one when `company` is given. */
export function CompanySheet({
  open,
  onClose,
  company,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  company?: CompanyPublic
  onSaved?: (company: CompanyPublic) => void
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={company ? "Edit company" : "New company"}
      description={company ? undefined : "An organisation you sell to."}
    >
      <CompanyForm key={String(open)} company={company} onClose={onClose} onSaved={onSaved} />
    </Sheet>
  )
}

function CompanyForm({
  company,
  onClose,
  onSaved,
}: {
  company?: CompanyPublic
  onClose: () => void
  onSaved?: (company: CompanyPublic) => void
}) {
  const { user } = useAuth()
  const { isAdmin } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [initial] = useState<Values>(() => ({
    name: company?.name ?? "",
    domain: company?.domain ?? "",
    industry: company?.industry ?? "",
    phone: company?.phone ?? "",
    owner_id: company?.owner_id ?? user?.id ?? null,
    fields: toFieldRows(company?.custom_fields),
  }))
  const [v, setV] = useState(initial)
  useUnsavedChanges(JSON.stringify(v) !== JSON.stringify(initial))
  const set = (patch: Partial<Values>) => setV({ ...v, ...patch })

  const done = (saved: CompanyPublic) => {
    invalidate(queryClient, ...RECORD_QUERIES)
    toast(company ? "Company saved" : `Added ${saved.name}`)
    onSaved?.(saved)
    onClose()
  }
  const onError = (e: unknown) => setError(apiErrorMessage(e))
  const create = useMutation({ ...companiesCreateCompanyMutation(), onSuccess: done, onError })
  const update = useMutation({ ...companiesUpdateCompanyMutation(), onSuccess: done, onError })
  const busy = create.isPending || update.isPending

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const custom = fromFieldRows(v.fields)
    if (custom.error) return setError(custom.error)
    const body = {
      name: v.name.trim(),
      domain: cleanDomain(v.domain),
      industry: orNull(v.industry),
      phone: orNull(v.phone),
      custom_fields: custom.fields,
      ...(isAdmin && v.owner_id ? { owner_id: v.owner_id } : {}),
    }
    if (!company) return create.mutate({ body })
    const changes = changedFields(body, company)
    if (Object.keys(changes).length === 0) return onClose()
    update.mutate({ path: { company_id: company.id }, body: changes })
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col space-y-4">
      <Field label="Name" htmlFor="company-name">
        <Input
          id="company-name"
          required
          maxLength={255}
          autoFocus
          autoComplete="off"
          value={v.name}
          onChange={(e) => set({ name: e.target.value })}
        />
      </Field>
      <Field label="Website" htmlFor="company-domain">
        <Input
          id="company-domain"
          maxLength={255}
          placeholder="acme.in"
          autoComplete="off"
          value={v.domain}
          onChange={(e) => set({ domain: e.target.value })}
        />
      </Field>
      <Field label="Industry" htmlFor="company-industry">
        <Input
          id="company-industry"
          maxLength={100}
          placeholder="e.g. Manufacturing"
          value={v.industry}
          onChange={(e) => set({ industry: e.target.value })}
        />
      </Field>
      <Field label="Phone" htmlFor="company-phone">
        <Input
          id="company-phone"
          type="tel"
          maxLength={50}
          autoComplete="off"
          value={v.phone}
          onChange={(e) => set({ phone: e.target.value })}
        />
      </Field>
      {isAdmin && (
        <Field label="Owner" htmlFor="company-owner">
          <OwnerSelect
            id="company-owner"
            value={v.owner_id}
            onChange={(owner_id) => set({ owner_id })}
          />
        </Field>
      )}
      <CustomFieldsEditor rows={v.fields} onChange={(fields) => set({ fields })} />
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <SheetFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : company ? "Save" : "Add company"}
        </Button>
      </SheetFooter>
    </form>
  )
}
