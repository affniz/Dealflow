import {
  Building2,
  ChartColumn,
  Inbox,
  ListChecks,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  SquareKanban,
  Users,
  X,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"

import { copilotListProposalsOptions } from "@/client/@tanstack/react-query.gen"
import { CopilotPanel } from "@/components/copilot/CopilotPanel"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/card"
import { permissions, useAuth } from "@/lib/auth"
import { cn, initials } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Pipeline", icon: SquareKanban, end: true, alsoActive: "/deals/" },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/companies", label: "Companies", icon: Building2 },
  { to: "/activities", label: "My activities", icon: ListChecks },
  { to: "/dashboard", label: "Dashboard", icon: ChartColumn },
  { to: "/inbox", label: "Agent inbox", icon: Inbox },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const { isAdmin } = permissions(user)
  const [open, setOpen] = useState(false)
  const [copilotOpen, setCopilotOpen] = useState(false)
  const { pathname } = useLocation()
  const pending = useQuery({
    ...copilotListProposalsOptions({ query: { status: "pending" } }),
    refetchInterval: 60_000,
  })
  const pendingCount = pending.data?.length ?? 0
  const name = user?.full_name || user?.email || ""
  const nav = isAdmin ? [...NAV, { to: "/settings", label: "Settings", icon: Settings }] : NAV

  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-3" aria-label="Main">
      <div className="mb-4 flex items-center gap-2 px-2 pt-1 text-lg font-semibold tracking-tight">
        <span className="grid size-7 place-items-center rounded-md bg-brand-600 text-sm text-white">
          D
        </span>
        Dealflow
      </div>
      {nav.map(({ to, label, icon: Icon, end, alsoActive }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive || (alsoActive && pathname.startsWith(alsoActive))
                ? "bg-brand-50 text-brand-700"
                : "text-ink-soft hover:bg-muted hover:text-ink",
            )
          }
        >
          <Icon className="size-4" />
          <span className="flex-1">{label}</span>
          {to === "/inbox" && pendingCount > 0 && (
            <span
              className="rounded-full bg-brand-600 px-1.5 text-xs font-semibold text-white"
              aria-label={`${pendingCount} waiting`}
            >
              {pendingCount}
            </span>
          )}
        </NavLink>
      ))}
      <Button
        variant="outline"
        className="mt-auto mb-2 justify-start"
        onClick={() => {
          setOpen(false)
          setCopilotOpen(true)
        }}
      >
        <Sparkles className="text-brand-600" /> Ask Copilot
      </Button>
      <div className="flex items-center gap-3 rounded-md border border-line p-2">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold">
          {initials(name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          <Badge className="capitalize">{user?.role}</Badge>
        </div>
        <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out" title="Sign out">
          <LogOut />
        </Button>
      </div>
    </nav>
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface md:block">
        {sidebar}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            className="absolute inset-0 bg-black/40"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-64 bg-surface shadow-xl">{sidebar}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line bg-surface px-4 py-2 md:hidden">
          <Button variant="ghost" size="icon" onClick={() => setOpen(!open)} aria-label="Menu">
            {open ? <X /> : <Menu />}
          </Button>
          <span className="flex-1 font-semibold">Dealflow</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Ask Copilot"
            onClick={() => setCopilotOpen(true)}
          >
            <Sparkles className="text-brand-600" />
          </Button>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <CopilotPanel open={copilotOpen} onClose={() => setCopilotOpen(false)} />
    </div>
  )
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-5 pb-4 md:px-6">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {children}
    </div>
  )
}
