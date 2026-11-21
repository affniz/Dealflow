import { type FormEvent, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Navigate, useLocation } from "react-router-dom"

import { configReadConfigOptions } from "@/client/@tanstack/react-query.gen"
import type { DemoAccount } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input, Label } from "@/components/ui/input"
import { useAuth } from "@/lib/auth"

export function LoginPage() {
  const { login, isAuthenticated } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const config = useQuery({ ...configReadConfigOptions(), staleTime: Infinity })
  const demo = config.data?.demo ? config.data : undefined

  if (isAuthenticated) {
    const from = (location.state as { from?: string } | null)?.from ?? "/"
    return <Navigate to={from} replace />
  }

  async function signIn(email: string, password: string) {
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in")
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void signIn(email, password)
  }

  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2 text-2xl font-semibold tracking-tight">
          <span className="grid size-9 place-items-center rounded-lg bg-brand-600 text-white">
            D
          </span>
          Dealflow
        </div>
        {demo && (
          <Card className="mb-4 p-6">
            <h2 className="text-lg font-semibold">Try the demo</h2>
            <p className="mt-1 text-sm text-ink-soft">
              Sign in as someone on a sample sales team. Each role sees something different.
              Everything is shared with other visitors.
            </p>
            <div className="mt-4 space-y-2">
              {demo.demo_accounts?.map((account) => (
                <DemoButton
                  key={account.email}
                  account={account}
                  disabled={busy}
                  onClick={() => void signIn(account.email, demo.demo_password ?? "")}
                />
              ))}
            </div>
          </Card>
        )}
        <Card className="p-6">
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-ink-soft">Use your work email and password.</p>
          <form className="mt-5 space-y-4" onSubmit={onSubmit}>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}

const ROLE_NOTES: Record<string, string> = {
  owner: "Owner: everything",
  admin: "Admin: the whole team, settings and AI usage",
  agent: "Sales agent: only their own deals and accounts",
  viewer: "Viewer: sees the whole team, changes nothing",
}

function DemoButton({
  account,
  disabled,
  onClick,
}: {
  account: DemoAccount
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center justify-between gap-3 rounded-md border border-line px-3 py-2 text-left transition-colors hover:bg-muted disabled:opacity-50"
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium">{account.full_name}</span>
        <span className="block text-xs text-ink-soft">
          {ROLE_NOTES[account.role] ?? account.role}
        </span>
      </span>
      <span className="shrink-0 text-sm font-medium text-brand-700">Sign in →</span>
    </button>
  )
}
