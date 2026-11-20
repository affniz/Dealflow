import { type ReactNode, useEffect, useRef, useState } from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SheetDirtyContext } from "@/lib/sheet"

/**
 * A panel that slides in from the right, for editing a record without leaving the page.
 * Built on the native <dialog> like Dialog: focus trapping, Escape and the backdrop come for free.
 * A form inside can call useUnsavedChanges so an accidental close asks first.
 */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [dirty, setDirty] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    setConfirming(false)
  }

  function requestClose() {
    if (dirty) setConfirming(true)
    else onClose()
  }

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        // Escape: route it through requestClose so unsaved changes aren't lost
        e.preventDefault()
        requestClose()
      }}
      onClick={(e) => e.target === ref.current && requestClose()}
      aria-labelledby="sheet-title"
      className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-md border-l border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40 open:animate-[sheet-in_160ms_ease-out]"
    >
      {open && (
        <div className="flex h-full flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <h2 id="sheet-title" className="text-base font-semibold">
                {title}
              </h2>
              {description && <p className="mt-1 text-sm text-ink-soft">{description}</p>}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="-mt-1 -mr-2"
              onClick={requestClose}
              aria-label="Close"
            >
              <X />
            </Button>
          </div>
          {confirming && (
            <div
              role="alertdialog"
              aria-label="Unsaved changes"
              className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              <span>Discard your changes?</span>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" autoFocus onClick={() => setConfirming(false)}>
                  Keep editing
                </Button>
                <Button size="sm" variant="destructive" onClick={onClose}>
                  Discard
                </Button>
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <SheetDirtyContext.Provider value={setDirty}>{children}</SheetDirtyContext.Provider>
          </div>
        </div>
      )}
    </dialog>
  )
}

/** Buttons pinned to the bottom of a sheet; the form around them should fill the sheet's height. */
export function SheetFooter({ children }: { children: ReactNode }) {
  return (
    <div className="sticky -bottom-4 mt-auto pt-6">
      <div className="-mx-5 flex items-center justify-end gap-2 border-t border-line bg-surface px-5 py-3">
        {children}
      </div>
    </div>
  )
}
