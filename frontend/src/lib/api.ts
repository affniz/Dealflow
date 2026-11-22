import type { QueryClient } from "@tanstack/react-query"

/** Turn a FastAPI error body into a sentence a person can act on. */
export function apiErrorMessage(error: unknown, fallback = "Something went wrong") {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: string }
    const field = first.loc?.at(-1)
    return field ? `${String(field).replaceAll("_", " ")}: ${first.msg}` : (first.msg ?? fallback)
  }
  return error instanceof Error ? error.message : fallback
}

/**
 * Refetch every cached query from these generated endpoints, whatever their parameters.
 * Generated query keys look like [{ _id: "dealsReadDeal", path: {...}, ... }].
 */
export function invalidate(queryClient: QueryClient, ...ids: string[]) {
  return queryClient.invalidateQueries({
    predicate: (q) => ids.includes((q.queryKey[0] as { _id?: string } | undefined)?._id ?? ""),
  })
}

/** Everything that shows deal data: call after any change to a deal or its activities. */
export const DEAL_QUERIES = [
  "boardPipelineBoard",
  "dealsReadDeal",
  "dealsDealTimeline",
  "dealsListDeals",
  "activitiesListActivities",
  "dashboardPipelineSummary",
  "dashboardLostReasons",
  "copilotListProposals",
  "trashListTrash",
]

/** Everything that shows contacts or companies (deals show their names too). */
export const RECORD_QUERIES = [
  "contactsListContacts",
  "contactsReadContact",
  "companiesListCompanies",
  "companiesReadCompany",
  "contactsContactHistory",
  "companiesCompanyHistory",
  ...DEAL_QUERIES,
]
