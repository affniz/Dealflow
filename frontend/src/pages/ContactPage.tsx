import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Mail, Pencil, Phone, Trash2 } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"

import {
  contactsContactHistoryOptions,
  contactsDeleteContactMutation,
  contactsReadContactOptions,
} from "@/client/@tanstack/react-query.gen"
import { RecordActivities } from "@/components/activities/RecordActivities"
import { ContactSheet } from "@/components/records/ContactSheet"
import { DetailsCard, NotFound } from "@/components/records/Details"
import { RecordDeals } from "@/components/records/RecordDeals"
import { RecordHistory } from "@/components/records/RecordHistory"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm"
import { RECORD_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { useToast } from "@/lib/toast"
import { initials } from "@/lib/utils"

export function ContactPage() {
  const contactId = Number(useParams().contactId)
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const [dialog, setDialog] = useState<"edit" | "delete" | null>(null)
  const contact = useQuery(contactsReadContactOptions({ path: { contact_id: contactId } }))
  const history = useQuery(contactsContactHistoryOptions({ path: { contact_id: contactId } }))
  const remove = useMutation({
    ...contactsDeleteContactMutation(),
    onSuccess: () => {
      invalidate(queryClient, ...RECORD_QUERIES)
      toast("Contact deleted")
      navigate("/contacts", { replace: true })
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })

  const back = (
    <Link
      to="/contacts"
      className="inline-flex items-center gap-1 text-sm text-ink-soft hover:text-ink"
    >
      <ArrowLeft className="size-4" /> Contacts
    </Link>
  )

  if (contact.isPending) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner />
      </div>
    )
  }
  if (contact.isError) return <NotFound what="contact" back={back} />

  const c = contact.data
  const name = [c.first_name, c.last_name].filter(Boolean).join(" ")
  const ref = { id: c.id, name }

  return (
    <div className="mx-auto max-w-6xl px-4 py-5 md:px-6">
      {back}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-full bg-brand-50 text-base font-semibold text-brand-700">
            {initials(name)}
          </span>
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
            <p className="text-sm text-ink-soft">
              {c.job_title}
              {c.job_title && c.company && " at "}
              {c.company && (
                <Link to={`/companies/${c.company.id}`} className="text-brand-700 hover:underline">
                  {c.company.name}
                </Link>
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {c.email && (
            <a
              href={`mailto:${c.email}`}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-muted"
            >
              <Mail className="size-4" /> Email
            </a>
          )}
          {c.phone && (
            <a
              href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-muted"
            >
              <Phone className="size-4" /> Call
            </a>
          )}
          {canWrite && (
            <>
              <Button variant="outline" onClick={() => setDialog("edit")}>
                <Pencil /> Edit
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete contact"
                title="Delete contact"
                onClick={() => setDialog("delete")}
              >
                <Trash2 />
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RecordActivities
            filter={{ contact_id: c.id }}
            links={{ contact_id: c.id, company_id: c.company_id }}
            hide={["contact"]}
            canWrite={canWrite}
          />
        </div>
        <div className="space-y-4">
          <DetailsCard
            rows={[
              [
                "Email",
                c.email && (
                  <a href={`mailto:${c.email}`} className="hover:text-brand-700 hover:underline">
                    {c.email}
                  </a>
                ),
              ],
              ["Phone", c.phone],
              [
                "Company",
                c.company && (
                  <Link
                    to={`/companies/${c.company.id}`}
                    className="hover:text-brand-700 hover:underline"
                  >
                    {c.company.name}
                  </Link>
                ),
              ],
              ...(seesTeam ? [["Owner", c.owner?.name] as [string, string | undefined]] : []),
            ]}
            customFields={c.custom_fields}
            createdAt={c.created_at}
            updatedAt={c.updated_at}
          />
          <RecordDeals
            filter={{ contact_id: c.id }}
            contact={ref}
            company={c.company}
            canWrite={canWrite}
          />
          <RecordHistory items={history.data} isPending={history.isPending} noun="contact" />
        </div>
      </div>

      <ContactSheet open={dialog === "edit"} onClose={() => setDialog(null)} contact={c} />
      <ConfirmDialog
        open={dialog === "delete"}
        onClose={() => setDialog(null)}
        onConfirm={() => remove.mutate({ path: { contact_id: c.id } })}
        busy={remove.isPending}
        title={`Delete ${name}?`}
        description="It moves to Recently deleted, where it can be restored, with its links to deals and activities, for 30 days."
        confirmLabel="Delete contact"
      />
    </div>
  )
}
