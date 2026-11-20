import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Building2, Plus } from "lucide-react"
import { useCallback, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { companiesListCompaniesOptions } from "@/client/@tanstack/react-query.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { CompanySheet } from "@/components/records/CompanySheet"
import { OwnerFilter, SortSelect } from "@/components/records/filters"
import { ownerQuery } from "@/lib/forms"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { EmptyState, Pager, SearchBox } from "@/components/ui/list"
import { useListParams } from "@/lib/listParams"
import { permissions, useAuth } from "@/lib/auth"
import { cn, formatMoneyShort } from "@/lib/utils"

const PAGE_SIZE = 50

export function CompaniesPage() {
  const { user } = useAuth()
  const { canWrite, seesTeam } = permissions(user)
  const navigate = useNavigate()
  const { params, set, page } = useListParams()
  const [adding, setAdding] = useState(false)
  const q = params.get("q") ?? ""
  const owner = params.get("owner") ?? "all"
  const sort = params.get("sort") === "recent" ? "recent" : "name"

  const companies = useQuery({
    ...companiesListCompaniesOptions({
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
      <PageHeader title="Companies">
        {canWrite && (
          <Button onClick={() => setAdding(true)}>
            <Plus /> New company
          </Button>
        )}
      </PageHeader>
      <div className="space-y-3 px-4 pb-6 md:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <SearchBox
            label="Search companies"
            placeholder="Name, website or industry"
            value={q}
            onChange={onSearch}
          />
          {seesTeam && (
            <OwnerFilter value={owner} onChange={(v) => set({ owner: v === "all" ? null : v })} />
          )}
          <SortSelect value={sort} onChange={(v) => set({ sort: v === "name" ? null : v })} />
        </div>

        <Card className="overflow-hidden">
          {companies.isPending ? (
            <div className="grid place-items-center p-12">
              <Spinner />
            </div>
          ) : companies.isError ? (
            <EmptyState title="Couldn't load companies.">Try reloading the page.</EmptyState>
          ) : companies.data.count === 0 ? (
            filtered ? (
              <EmptyState title="No companies match.">Try a different search or filter.</EmptyState>
            ) : (
              <EmptyState title="No companies yet.">
                {canWrite ? "Add the organisations you sell to." : "Nobody has added any yet."}
              </EmptyState>
            )
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-muted/50 text-left text-xs text-ink-soft">
                <tr>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Industry</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">People</th>
                  <th className="px-4 py-2 text-right font-medium">Open deals</th>
                  {seesTeam && (
                    <th className="hidden px-4 py-2 font-medium lg:table-cell">Owner</th>
                  )}
                </tr>
              </thead>
              <tbody
                className={cn("divide-y divide-line", companies.isPlaceholderData && "opacity-60")}
              >
                {companies.data.data.map((c) => (
                  <tr
                    key={c.id}
                    className="cursor-pointer hover:bg-muted/60"
                    onClick={(e) => {
                      if (!(e.target as HTMLElement).closest("a")) navigate(`/companies/${c.id}`)
                    }}
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-3">
                        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-ink-soft">
                          <Building2 className="size-4" />
                        </span>
                        <div className="min-w-0">
                          <Link
                            to={`/companies/${c.id}`}
                            className="block truncate font-medium hover:text-brand-700"
                          >
                            {c.name}
                          </Link>
                          {c.domain && (
                            <div className="truncate text-xs text-ink-soft">{c.domain}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="hidden px-4 py-2.5 text-ink-soft md:table-cell">
                      {c.industry ?? <span className="text-ink-faint">—</span>}
                    </td>
                    <td className="hidden px-4 py-2.5 text-right tabular-nums sm:table-cell">
                      {c.contact_count || <span className="text-ink-faint">0</span>}
                    </td>
                    <td className="px-4 py-2.5 text-right whitespace-nowrap tabular-nums">
                      {c.open_deal_count ? (
                        <>
                          {c.open_deal_count}
                          <span className="ml-2 text-ink-soft">
                            {formatMoneyShort(c.open_deal_value)}
                          </span>
                        </>
                      ) : (
                        <span className="text-ink-faint">0</span>
                      )}
                    </td>
                    {seesTeam && (
                      <td className="hidden px-4 py-2.5 text-ink-soft lg:table-cell">
                        {c.owner?.name}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {companies.data && (
          <Pager
            page={page}
            pageSize={PAGE_SIZE}
            count={companies.data.count}
            onPage={(p) => set({ page: p === 1 ? null : p })}
          />
        )}
      </div>
      <CompanySheet
        open={adding}
        onClose={() => setAdding(false)}
        onSaved={(c) => navigate(`/companies/${c.id}`)}
      />
    </>
  )
}
