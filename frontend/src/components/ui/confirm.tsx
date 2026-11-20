import { Button } from "@/components/ui/button"
import { Dialog, DialogFooter } from "@/components/ui/dialog"

/** "Are you sure?" for destructive actions. */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel,
  busy,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description: string
  confirmLabel: string
  busy?: boolean
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title} description={description}>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="destructive" disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
