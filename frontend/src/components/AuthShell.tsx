import type { ReactNode } from "react"

/** The centred, logo-topped layout of the signed-out pages. */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2 text-2xl font-semibold tracking-tight">
          <span className="grid size-9 place-items-center rounded-lg bg-brand-600 text-white">
            D
          </span>
          Dealflow
        </div>
        {children}
      </div>
    </div>
  )
}
