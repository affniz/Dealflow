import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useCallback, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { contactsListContactsOptions } from "@/client/@tanstack/react-query.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { ContactSheet } from "@/components/records/ContactSheet"
import { OwnerFilter, SortSelect } from "@/components/records/filters"
import { ownerQuery } from "@/lib/forms"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { EmptyState, Pager, SearchBox } from "@/components/ui/list"
import { useListParams } from "@/lib/listParams"
import { permissions, useAuth } from "@/lib/auth"
import { initials } from "@/lib/utils"

const PAGE_SIZE = 50

export function ContactsPage() {
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const navigate = useNavigate()
  const { params, set, page } = useListParams()
  const [adding, setAdding] = useState(false)
  const q = params.get("q") ?? ""
  const owner = params.get("owner") ?? "all"
  const sort = params.get("sort") === "recent" ? "recent" : "name"

  const contacts = useQuery({
    ...contactsListContactsOptions({
      query: {
        q: q || undefined,
        owner_id: ownerQuery(owner, user?.id),
        sort,
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      },
    }),
    placeholderData: keepPreviousData,
  })
  const onSearch = useCallback((value: string) => set({ q: value }), [set])
  const filtered = Boolean(q) || owner !== "all"

  return (
    <>
      <PageHeader title="Contacts">
        {canWrite && (
          <Button onClick={() => setAdding(true)}>
            <Plus /> New contact
          </Button>
        )}
      </PageHeader>
      <div className="space-y-3 px-4 pb-6 md:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <SearchBox
            label="Search contacts"
            placeholder="Name, email, phone or company"
            value={q}
            onChange={onSearch}
          />
          {seesTeam && (
            <OwnerFilter value={owner} onChange={(v) => set({ owner: v === "all" ? null : v })} />
          )}
          <SortSelect value={sort} onChange={(v) => set({ sort: v === "name" ? null : v })} />
        </div>

        <Card className="overflow-hidden">
          {contacts.isPending ? (
            <div className="grid place-items-center p-12">
              <Spinner />
            </div>
          ) : contacts.isError ? (
            <EmptyState title="Couldn't load contacts.">Try reloading the page.</EmptyState>
          ) : contacts.data.count === 0 ? (
            filtered ? (
              <EmptyState title="No contacts match.">Try a different search or filter.</EmptyState>
            ) : (
              <EmptyState title="No contacts yet.">
                {canWrite ? "Add the people you sell to." : "Nobody has added any yet."}
              </EmptyState>
            )
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-muted/50 text-left text-xs text-ink-soft">
                <tr>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Company</th>
                  <th className="hidden px-4 py-2 font-medium lg:table-cell">Email</th>
                  <th className="hidden px-4 py-2 font-medium lg:table-cell">Phone</th>
                  <th className="hidden px-4 py-2 text-right font-medium whitespace-nowrap md:table-cell">
                    Open deals
                  </th>
                  {seesTeam && (
                    <th className="hidden px-4 py-2 font-medium xl:table-cell">Owner</th>
                  )}
                </tr>
              </thead>
              <tbody
                className={
                  contacts.isPlaceholderData
                    ? "divide-y divide-line opacity-60"
                    : "divide-y divide-line"
                }
              >
                {contacts.data.data.map((c) => {
                  const name = [c.first_name, c.last_name].filter(Boolean).join(" ")
                  return (
                    <tr
                      key={c.id}
                      className="cursor-pointer hover:bg-muted/60"
                      onClick={(e) => {
                        // links inside the row keep their own destination
                        if (!(e.target as HTMLElement).closest("a")) navigate(`/contacts/${c.id}`)
                      }}
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-3">
                          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-ink-soft">
                            {initials(name)}
                          </span>
                          <div className="min-w-0">
                            <Link
                              to={`/contacts/${c.id}`}
                              className="block truncate font-medium hover:text-brand-700"
                            >
                              {name}
                            </Link>
                            <div className="truncate text-xs text-ink-soft">
                              {c.job_title}
                              {/* on phones the company column is hidden: show it here */}
                              <span className="sm:hidden">
                                {c.job_title && c.company ? " · " : ""}
                                {c.company?.name}
                              </span>
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="hidden px-4 py-2.5 sm:table-cell">
                        {c.company ? (
                          <Link
                            to={`/companies/${c.company.id}`}
                            className="hover:text-brand-700 hover:underline"
                          >
                            {c.company.name}
                          </Link>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </td>
                      <td className="hidden max-w-60 truncate px-4 py-2.5 text-ink-soft lg:table-cell">
                        {c.email ?? <span className="text-ink-faint">—</span>}
                      </td>
                      <td className="hidden px-4 py-2.5 whitespace-nowrap text-ink-soft lg:table-cell">
                        {c.phone ?? <span className="text-ink-faint">—</span>}
                      </td>
                      <td className="hidden px-4 py-2.5 text-right tabular-nums md:table-cell">
                        {c.open_deal_count || <span className="text-ink-faint">0</span>}
                      </td>
                      {seesTeam && (
                        <td className="hidden px-4 py-2.5 text-ink-soft xl:table-cell">
                          {c.owner?.name}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Card>
        {contacts.data && (
          <Pager
            page={page}
            pageSize={PAGE_SIZE}
            count={contacts.data.count}
            onPage={(p) => set({ page: p === 1 ? null : p })}
          />
        )}
      </div>
      <ContactSheet
        open={adding}
        onClose={() => setAdding(false)}
        onSaved={(c) => navigate(`/contacts/${c.id}`)}
      />
    </>
  )
}
