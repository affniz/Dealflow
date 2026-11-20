import { type ReactNode, useEffect, useRef } from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** Modal built on the native <dialog>: focus trapping, Escape and the backdrop come for free. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className,
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      // React's autoFocus runs before the dialog opens, so showModal() would focus the close
      // button and Enter would close the dialog; start in the first field instead
      dialog
        .querySelector<HTMLElement>(
          "input:not([type=hidden]):not(:disabled), select:not(:disabled), textarea:not(:disabled)",
        )
        ?.focus()
    } else if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="dialog-title"
      className={cn(
        "m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40",
        className,
      )}
    >
      {open && (
        <div className="p-5">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 id="dialog-title" className="text-base font-semibold">
                {title}
              </h2>
              {description && <p className="mt-1 text-sm text-ink-soft">{description}</p>}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="-mt-1 -mr-2"
              onClick={onClose}
              aria-label="Close"
            >
              <X />
            </Button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  )
}

export function DialogFooter({ children }: { children: ReactNode }) {
  return <div className="mt-5 flex justify-end gap-2">{children}</div>
}
