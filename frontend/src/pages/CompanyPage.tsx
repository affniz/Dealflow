import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Building2, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"

import {
  companiesDeleteCompanyMutation,
  companiesReadCompanyOptions,
  contactsListContactsOptions,
} from "@/client/@tanstack/react-query.gen"
import type { NamedRef } from "@/client/types.gen"
import { RecordActivities } from "@/components/activities/RecordActivities"
import { CompanySheet } from "@/components/records/CompanySheet"
import { ContactSheet } from "@/components/records/ContactSheet"
import { DetailsCard, NotFound } from "@/components/records/Details"
import { RecordDeals } from "@/components/records/RecordDeals"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm"
import { RECORD_QUERIES, apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { useToast } from "@/lib/toast"
import { formatMoney, initials } from "@/lib/utils"

export function CompanyPage() {
  const companyId = Number(useParams().companyId)
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const [dialog, setDialog] = useState<"edit" | "delete" | "person" | null>(null)
  const company = useQuery(companiesReadCompanyOptions({ path: { company_id: companyId } }))
  const remove = useMutation({
    ...companiesDeleteCompanyMutation(),
    onSuccess: () => {
      invalidate(queryClient, ...RECORD_QUERIES)
      toast("Company deleted")
      navigate("/companies", { replace: true })
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })

  const back = (
    <Link
      to="/companies"
      className="inline-flex items-center gap-1 text-sm text-ink-soft hover:text-ink"
    >
      <ArrowLeft className="size-4" /> Companies
    </Link>
  )

  if (company.isPending) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner />
      </div>
    )
  }
  if (company.isError) return <NotFound what="company" back={back} />

  const c = company.data
  const ref = { id: c.id, name: c.name }

  return (
    <div className="mx-auto max-w-6xl px-4 py-5 md:px-6">
      {back}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
            <Building2 className="size-6" />
          </span>
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{c.name}</h1>
            <p className="text-sm text-ink-soft">
              {[c.industry, c.domain].filter(Boolean).join(" · ") || "No industry or website"}
            </p>
          </div>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setDialog("edit")}>
              <Pencil /> Edit
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete company"
              title="Delete company"
              onClick={() => setDialog("delete")}
            >
              <Trash2 />
            </Button>
          </div>
        )}
      </div>

      <dl className="mt-5 grid grid-cols-3 gap-3 sm:max-w-lg">
        <Stat label="People" value={String(c.contact_count ?? 0)} />
        <Stat label="Open deals" value={String(c.open_deal_count ?? 0)} />
        <Stat label="Open value" value={formatMoney(c.open_deal_value)} />
      </dl>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RecordActivities
            filter={{ company_id: c.id }}
            links={{ company_id: c.id }}
            hide={["company"]}
            canWrite={canWrite}
          />
        </div>
        <div className="space-y-4">
          <People company={ref} canWrite={canWrite} onAdd={() => setDialog("person")} />
          <RecordDeals filter={{ company_id: c.id }} company={ref} canWrite={canWrite} />
          <DetailsCard
            rows={[
              [
                "Website",
                c.domain && (
                  <a
                    href={`https://${c.domain}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 hover:text-brand-700 hover:underline"
                  >
                    {c.domain} <ExternalLink className="size-3" />
                  </a>
                ),
              ],
              ["Industry", c.industry],
              [
                "Phone",
                c.phone && (
                  <a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`} className="hover:underline">
                    {c.phone}
                  </a>
                ),
              ],
              ...(seesTeam ? [["Owner", c.owner?.name] as [string, string | undefined]] : []),
            ]}
            customFields={c.custom_fields}
            createdAt={c.created_at}
            updatedAt={c.updated_at}
          />
        </div>
      </div>

      <CompanySheet open={dialog === "edit"} onClose={() => setDialog(null)} company={c} />
      <ContactSheet open={dialog === "person"} onClose={() => setDialog(null)} company={ref} />
      <ConfirmDialog
        open={dialog === "delete"}
        onClose={() => setDialog(null)}
        onConfirm={() => remove.mutate({ path: { company_id: c.id } })}
        busy={remove.isPending}
        title={`Delete ${c.name}?`}
        description="Its people, deals and activities stay, without the link to this company. This can't be undone."
        confirmLabel="Delete company"
      />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="px-3 py-2">
      <dt className="text-xs text-ink-soft">{label}</dt>
      <dd className="truncate text-lg font-semibold tabular-nums">{value}</dd>
    </Card>
  )
}

function People({
  company,
  canWrite,
  onAdd,
}: {
  company: NamedRef
  canWrite: boolean
  onAdd: () => void
}) {
  const people = useQuery(
    contactsListContactsOptions({ query: { company_id: company.id, limit: 100 } }),
  )
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          People{people.data && people.data.count > 0 ? ` · ${people.data.count}` : ""}
        </h2>
        {canWrite && (
          <Button variant="ghost" size="sm" onClick={onAdd}>
            <Plus /> Add
          </Button>
        )}
      </div>
      {people.isPending ? (
        <Spinner />
      ) : !people.data || people.data.count === 0 ? (
        <p className="text-sm text-ink-faint">No one from {company.name} yet.</p>
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {people.data.data.map((p) => {
            const name = [p.first_name, p.last_name].filter(Boolean).join(" ")
            return (
              <li key={p.id}>
                <Link
                  to={`/contacts/${p.id}`}
                  className="flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
                >
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold text-ink-soft">
                    {initials(name)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{name}</p>
                    {p.job_title && <p className="truncate text-xs text-ink-soft">{p.job_title}</p>}
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
