import { useMutation, useQuery } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"
import { Link } from "react-router-dom"

import {
  configReadConfigOptions,
  loginRecoverPasswordMutation,
  loginResetForgottenPasswordMutation,
} from "@/client/@tanstack/react-query.gen"
import { AuthShell } from "@/components/AuthShell"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input, Label } from "@/components/ui/input"
import { apiErrorMessage } from "@/lib/api"

function BackToSignIn() {
  return (
    <p className="mt-4 text-center text-sm">
      <Link to="/login" className="text-brand-700 hover:underline">
        Back to sign in
      </Link>
    </p>
  )
}

/** "Forgot your password?": emails a one-time reset link. */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const config = useQuery({ ...configReadConfigOptions(), staleTime: Infinity })
  const recover = useMutation(loginRecoverPasswordMutation())

  function submit(e: FormEvent) {
    e.preventDefault()
    recover.mutate({ body: { email } })
  }

  return (
    <AuthShell>
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Reset your password</h1>
        {config.data && !config.data.password_reset_email ? (
          <p className="mt-2 text-sm text-ink-soft">
            Email isn't set up here, so ask an admin on your team for a password reset link.
          </p>
        ) : recover.isSuccess ? (
          <p role="status" className="mt-2 text-sm text-ink-soft">
            {recover.data.message} It works once, for the next hour. Nothing there? Check the
            address and your spam folder, or ask an admin for a link.
          </p>
        ) : (
          <>
            <p className="mt-1 text-sm text-ink-soft">
              We'll email you a link to choose a new password.
            </p>
            <form className="mt-5 space-y-4" onSubmit={submit}>
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
              {recover.isError && (
                <p role="alert" className="text-sm text-red-600">
                  {apiErrorMessage(recover.error)}
                </p>
              )}
              <Button type="submit" className="w-full" disabled={recover.isPending}>
                {recover.isPending ? "Sending…" : "Email me a link"}
              </Button>
            </form>
          </>
        )}
      </Card>
      <BackToSignIn />
    </AuthShell>
  )
}

/** Read the link's secret from after the #, then take it out of the address bar and history. */
function useTokenFromLink() {
  const [token] = useState(() => {
    const value = window.location.hash.slice(1)
    if (value) window.history.replaceState(null, "", window.location.pathname)
    return value
  })
  return token
}

/** Where a reset link lands: choose a new password. */
export function ResetPasswordPage() {
  const token = useTokenFromLink()
  const [v, setV] = useState({ next: "", again: "" })
  const [error, setError] = useState<string | null>(null)
  const reset = useMutation({
    ...loginResetForgottenPasswordMutation(),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (v.next !== v.again) return setError("The new passwords don't match")
    reset.mutate({ body: { token, new_password: v.next } })
  }

  return (
    <AuthShell>
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Choose a new password</h1>
        {!token ? (
          <p className="mt-2 text-sm text-ink-soft">
            This page needs the whole reset link. Open the link again, or ask for a new one.
          </p>
        ) : reset.isSuccess ? (
          <p role="status" className="mt-2 text-sm text-ink-soft">
            {reset.data.message} You've been signed out everywhere else.
          </p>
        ) : (
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="pw-new">New password</Label>
              <Input
                id="pw-new"
                type="password"
                required
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                value={v.next}
                onChange={(e) => setV({ ...v, next: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-again">New password again</Label>
              <Input
                id="pw-again"
                type="password"
                required
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                value={v.again}
                onChange={(e) => setV({ ...v, again: e.target.value })}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={reset.isPending}>
              {reset.isPending ? "Saving…" : "Set new password"}
            </Button>
          </form>
        )}
      </Card>
      <BackToSignIn />
    </AuthShell>
  )
}
