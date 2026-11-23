import { Spinner } from "@/components/ui/card"

/** Shown while the first page's code downloads. */
export function PageLoading() {
  return (
    <div className="grid h-full min-h-dvh place-items-center">
      <Spinner />
    </div>
  )
}
