import { createContext, useContext } from "react"

export type ToastTone = "default" | "error"
export type Toast = { id: number; message: string; tone: ToastTone }

export const ToastContext = createContext<((message: string, tone?: ToastTone) => void) | null>(
  null,
)

export function useToast() {
  const show = useContext(ToastContext)
  if (!show) throw new Error("useToast must be used inside ToastProvider")
  return show
}
