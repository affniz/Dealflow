import type { ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react"

import { Label } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const control =
  "w-full rounded-md border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-faint focus-visible:border-brand-600 focus-visible:outline-2 focus-visible:outline-brand-600/30 disabled:opacity-50"

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(control, "h-9 pr-8", className)} {...props} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(control, "min-h-20 py-2", className)} {...props} />
}

export function Field({
  label,
  htmlFor,
  children,
  className,
}: {
  label: string
  htmlFor: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}
