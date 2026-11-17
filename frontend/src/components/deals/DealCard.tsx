import { Flame } from "lucide-react"
import { Link } from "react-router-dom"

import type { DealPublic } from "@/client/types.gen"
import { Card } from "@/components/ui/card"
import { cn, formatMoney, initials } from "@/lib/utils"

export function DealCard({ deal, lifted }: { deal: DealPublic; lifted?: boolean }) {
  return (
    <Card
      className={cn(
        "p-3 transition-shadow",
        deal.is_rotting && "border-red-300 dark:border-red-800",
        lifted && "rotate-1 shadow-lg ring-2 ring-brand-600/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm leading-snug font-medium">
          <Link
            to={`/deals/${deal.id}`}
            className="hover:underline focus-visible:underline focus-visible:outline-none"
            draggable={false}
          >
            {deal.title}
          </Link>
        </h3>
        {deal.is_rotting && (
          <Flame className="size-4 shrink-0 text-red-500" aria-label="Stalled deal" />
        )}
      </div>
      {(deal.company || deal.contact) && (
        <p className="mt-1 truncate text-xs text-ink-soft">
          {[deal.company?.name, deal.contact?.name].filter(Boolean).join(" · ")}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between">
        <span className="text-sm font-semibold">
          {formatMoney(deal.value, deal.currency ?? "INR")}
        </span>
        {deal.owner && (
          <span
            className="grid size-6 place-items-center rounded-full bg-surface text-[10px] font-semibold ring-1 ring-line"
            title={deal.owner.name}
          >
            {initials(deal.owner.name)}
          </span>
        )}
      </div>
    </Card>
  )
}
