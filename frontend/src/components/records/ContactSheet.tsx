import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"

import {
  contactsCreateContactMutation,
  contactsUpdateContactMutation,
} from "@/client/@tanstack/react-query.gen"
import type { ContactPublic, NamedRef } from "@/client/types.gen"
import { CompanySelect, OwnerSelect } from "@/components/records/fields"
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
  first_name: string
  last_name: string
  email: string
  phone: string
  job_title: string
  company_id: number | null
  owner_id: number | null
  fields: FieldRow[]
}

/** Add a contact, or edit one when `contact` is given. */
export function ContactSheet({
  open,
  onClose,
  contact,
  company,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  contact?: ContactPublic
  /** For a new contact: start with this company picked. */
  company?: NamedRef
  onSaved?: (contact: ContactPublic) => void
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={contact ? "Edit contact" : "New contact"}
      description={contact ? undefined : "A person you sell to."}
    >
      <ContactForm
        key={String(open)}
        contact={contact}
        company={company}
        onClose={onClose}
        onSaved={onSaved}
      />
    </Sheet>
  )
}

function ContactForm({
  contact,
  company,
  onClose,
  onSaved,
}: {
  contact?: ContactPublic
  company?: NamedRef
  onClose: () => void
  onSaved?: (contact: ContactPublic) => void
}) {
  const { user } = useAuth()
  const { isAdmin } = permissions(user)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [initial] = useState<Values>(() => ({
    first_name: contact?.first_name ?? "",
    last_name: contact?.last_name ?? "",
    email: contact?.email ?? "",
    phone: contact?.phone ?? "",
    job_title: contact?.job_title ?? "",
    company_id: contact ? (contact.company_id ?? null) : (company?.id ?? null),
    owner_id: contact?.owner_id ?? user?.id ?? null,
    fields: toFieldRows(contact?.custom_fields),
  }))
  const [v, setV] = useState(initial)
  useUnsavedChanges(JSON.stringify(v) !== JSON.stringify(initial))
  const set = (patch: Partial<Values>) => setV({ ...v, ...patch })

  const done = (saved: ContactPublic) => {
    invalidate(queryClient, ...RECORD_QUERIES)
    toast(contact ? "Contact saved" : `Added ${saved.first_name}`)
    onSaved?.(saved)
    onClose()
  }
  const onError = (e: unknown) => setError(apiErrorMessage(e))
  const create = useMutation({ ...contactsCreateContactMutation(), onSuccess: done, onError })
  const update = useMutation({ ...contactsUpdateContactMutation(), onSuccess: done, onError })
  const busy = create.isPending || update.isPending

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const custom = fromFieldRows(v.fields)
    if (custom.error) return setError(custom.error)
    const body = {
      first_name: v.first_name.trim(),
      last_name: orNull(v.last_name),
      email: orNull(v.email),
      phone: orNull(v.phone),
      job_title: orNull(v.job_title),
      company_id: v.company_id,
      custom_fields: custom.fields,
      ...(isAdmin && v.owner_id ? { owner_id: v.owner_id } : {}),
    }
    if (!contact) return create.mutate({ body })
    // only what changed, so an untouched company link isn't re-checked
    const changes = changedFields(body, contact)
    if (Object.keys(changes).length === 0) return onClose()
    update.mutate({ path: { contact_id: contact.id }, body: changes })
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" htmlFor="contact-first">
          <Input
            id="contact-first"
            required
            maxLength={100}
            autoFocus
            autoComplete="off"
            value={v.first_name}
            onChange={(e) => set({ first_name: e.target.value })}
          />
        </Field>
        <Field label="Last name" htmlFor="contact-last">
          <Input
            id="contact-last"
            maxLength={100}
            autoComplete="off"
            value={v.last_name}
            onChange={(e) => set({ last_name: e.target.value })}
          />
        </Field>
      </div>
      <Field label="Job title" htmlFor="contact-title">
        <Input
          id="contact-title"
          maxLength={100}
          placeholder="e.g. Head of Procurement"
          value={v.job_title}
          onChange={(e) => set({ job_title: e.target.value })}
        />
      </Field>
      <Field label="Company" htmlFor="contact-company">
        <CompanySelect
          id="contact-company"
          value={v.company_id}
          current={contact?.company ?? company}
          onChange={(company_id) => set({ company_id })}
        />
      </Field>
      <Field label="Email" htmlFor="contact-email">
        <Input
          id="contact-email"
          type="email"
          maxLength={255}
          autoComplete="off"
          value={v.email}
          onChange={(e) => set({ email: e.target.value })}
        />
      </Field>
      <Field label="Phone" htmlFor="contact-phone">
        <Input
          id="contact-phone"
          type="tel"
          maxLength={50}
          placeholder="+91 98765 43210"
          autoComplete="off"
          value={v.phone}
          onChange={(e) => set({ phone: e.target.value })}
        />
      </Field>
      {isAdmin && (
        <Field label="Owner" htmlFor="contact-owner">
          <OwnerSelect
            id="contact-owner"
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
          {busy ? "Saving…" : contact ? "Save" : "Add contact"}
        </Button>
      </SheetFooter>
    </form>
  )
}
