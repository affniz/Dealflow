import { createContext, useContext, useEffect } from "react"

/** Lets a form inside a Sheet say whether it has unsaved changes. */
export const SheetDirtyContext = createContext<((dirty: boolean) => void) | null>(null)

/**
 * Call from a form inside a Sheet: while `dirty`, closing the sheet by accident (Escape, a click
 * outside it, the close button) asks before throwing the changes away. Cancel and Save don't.
 */
export function useUnsavedChanges(dirty: boolean) {
  const setDirty = useContext(SheetDirtyContext)
  useEffect(() => {
    setDirty?.(dirty)
    return () => setDirty?.(false)
  }, [setDirty, dirty])
}
