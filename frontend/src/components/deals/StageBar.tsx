import type { StagePublic } from "@/client/types.gen"
import { cn } from "@/lib/utils"

/** Pipeline progress for one deal; clicking a stage moves the deal there. */
export function StageBar({
  stages,
  currentId,
  disabled,
  onSelect,
}: {
  stages: StagePublic[]
  currentId: number
  disabled: boolean
  onSelect: (stageId: number) => void
}) {
  const currentIndex = stages.findIndex((s) => s.id === currentId)
  return (
    <ol className="flex overflow-x-auto rounded-md border border-line" aria-label="Stage">
      {stages.map((stage, i) => {
        const done = i < currentIndex
        const current = i === currentIndex
        return (
          <li key={stage.id} className="min-w-20 flex-1 sm:min-w-28">
            <button
              type="button"
              disabled={disabled || current}
              onClick={() => onSelect(stage.id)}
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex h-full w-full flex-col items-start border-r border-line px-2 py-2 text-left text-xs transition-colors last:border-r-0 sm:px-3",
                current && "bg-brand-600 text-white",
                done && "bg-brand-50 text-brand-700",
                !current && !done && "bg-surface text-ink-soft",
                !disabled && !current && "hover:bg-muted",
              )}
            >
              <span className="font-semibold">{stage.name}</span>
              <span className={cn(current ? "text-white/80" : "text-ink-faint")}>
                {stage.probability}%
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
