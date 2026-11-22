import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, Plus } from "lucide-react"
import { type FormEvent, type ReactNode, useState } from "react"

import {
  configReadConfigOptions,
  loginLogoutEverywhereMutation,
  tokensCreateTokenMutation,
  tokensListTokensOptions,
  tokensRevokeTokenMutation,
  usersChangePasswordMutation,
  usersReadMeOptions,
  usersUpdateMeMutation,
} from "@/client/@tanstack/react-query.gen"
import type { ApiTokenCreated, ApiTokenPublic } from "@/client/types.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { CopyBlock } from "@/components/ui/copy"
import { ConfirmDialog } from "@/components/ui/confirm"
import { Dialog, DialogFooter } from "@/components/ui/dialog"
import { Field } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { apiErrorMessage, invalidate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { formatDateTime } from "@/lib/time"
import { useToast } from "@/lib/toast"
import { timeAgo } from "@/lib/utils"

/** The signed-in person's own settings: name, password, and tokens for connecting Claude. */
export function AccountPage() {
  return (
    <>
      <PageHeader title="Your account" />
      <div className="max-w-3xl space-y-8 px-4 pb-8 md:px-6">
        <Profile />
        <Password />
        <SignOutEverywhere />
        <ConnectClaude />
      </div>
    </>
  )
}

function Section({
  id,
  title,
  description,
  action,
  children,
}: {
  id: string
  title: string
  description?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={id} className="text-base font-semibold">
            {title}
          </h2>
          {description && <p className="mt-1 max-w-2xl text-sm text-ink-soft">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function Profile() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState(user?.full_name ?? "")
  const save = useMutation({
    ...usersUpdateMeMutation(),
    onSuccess: (u) => {
      queryClient.setQueryData(usersReadMeOptions().queryKey, u)
      invalidate(queryClient, "usersUserDirectory", "usersListUsers")
      toast("Name saved")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const changed = name.trim() !== (user?.full_name ?? "")

  return (
    <Section id="profile" title="Profile">
      <Card className="p-4">
        <form
          className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate({ body: { full_name: name.trim() || null } })
          }}
        >
          <Field label="Name" htmlFor="account-name">
            <Input
              id="account-name"
              maxLength={255}
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="outline" disabled={!changed || save.isPending}>
            {save.isPending ? "Saving…" : "Save name"}
          </Button>
        </form>
        <dl className="mt-4 grid gap-1 text-sm sm:grid-cols-[6rem_1fr]">
          <dt className="text-ink-soft">Email</dt>
          <dd>{user?.email}</dd>
          <dt className="text-ink-soft">Role</dt>
          <dd className="capitalize">{user?.role}</dd>
        </dl>
      </Card>
    </Section>
  )
}

function Password() {
  const toast = useToast()
  const blank = { current: "", next: "", again: "" }
  const [v, setV] = useState(blank)
  const [error, setError] = useState<string | null>(null)
  const change = useMutation({
    ...usersChangePasswordMutation(),
    onSuccess: () => {
      setV(blank)
      toast("Password changed")
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (v.next !== v.again) return setError("The new passwords don't match")
    change.mutate({ body: { current_password: v.current, new_password: v.next } })
  }

  return (
    <Section
      id="password"
      title="Password"
      description="Changing it signs you out on every other device."
    >
      <Card className="p-4">
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-3">
          <Field label="Current password" htmlFor="pw-current">
            <Input
              id="pw-current"
              type="password"
              required
              autoComplete="current-password"
              value={v.current}
              onChange={(e) => setV({ ...v, current: e.target.value })}
            />
          </Field>
          <Field label="New password" htmlFor="pw-new">
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
          </Field>
          <Field label="New password again" htmlFor="pw-again">
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
          </Field>
          <div className="flex items-center justify-between gap-3 sm:col-span-3">
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
            <Button type="submit" variant="outline" disabled={change.isPending}>
              {change.isPending ? "Changing…" : "Change password"}
            </Button>
          </div>
        </form>
      </Card>
    </Section>
  )
}

/** Not in the public demo: its visitors share accounts, so it would sign out everyone. */
function SignOutEverywhere() {
  const { logout } = useAuth()
  const config = useQuery({ ...configReadConfigOptions(), staleTime: Infinity })
  const [confirming, setConfirming] = useState(false)
  const everywhere = useMutation({
    ...loginLogoutEverywhereMutation(),
    onSuccess: () => void logout(),
  })
  if (config.data?.demo !== false) return null

  return (
    <Section
      id="sessions"
      title="Signed-in devices"
      description="You stay signed in on a device until you sign out there, leave it unused for 12 hours, or 7 days pass. Lost a device, or signed in somewhere you shouldn't have? Sign out everywhere at once."
    >
      <Card className="flex justify-end p-4">
        <Button variant="outline" onClick={() => setConfirming(true)}>
          Sign out everywhere
        </Button>
      </Card>
      <ConfirmDialog
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={() => everywhere.mutate({}, { onSettled: () => setConfirming(false) })}
        busy={everywhere.isPending}
        title="Sign out everywhere?"
        description="Every browser and script signed in as you is signed out, this one included. Personal access tokens for Claude keep working; revoke those below."
        confirmLabel="Sign out everywhere"
      />
    </Section>
  )
}

/** Where MCP clients connect: the API serves it, and the dev server forwards it. */
function mcpUrl() {
  return `${window.location.origin}/mcp`
}

function ConnectClaude() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const tokens = useQuery(tokensListTokensOptions())
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)
  const [revoking, setRevoking] = useState<ApiTokenPublic | null>(null)
  const revoke = useMutation({
    ...tokensRevokeTokenMutation(),
    onSuccess: () => {
      invalidate(queryClient, "tokensListTokens")
      toast("Token revoked")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })

  return (
    <Section
      id="connect-claude"
      title="Connect Claude"
      description="Let Claude (Claude Code, Claude Desktop or any MCP client) work with Dealflow as you. It sees what you can see, and anything it wants to change arrives in your Agent inbox for you to approve."
      action={
        <Button variant="outline" onClick={() => setCreating(true)}>
          <Plus /> Create token
        </Button>
      }
    >
      <Card>
        {tokens.isPending ? (
          <div className="p-4">
            <Spinner />
          </div>
        ) : tokens.data?.length ? (
          <ul className="divide-y divide-line">
            {tokens.data.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <KeyRound className="size-4 shrink-0 text-ink-faint" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{t.name}</p>
                  <p className="text-xs text-ink-soft">
                    <span className="font-mono">{t.prefix}…</span> · created{" "}
                    <time dateTime={t.created_at} title={formatDateTime(t.created_at)}>
                      {timeAgo(t.created_at)}
                    </time>{" "}
                    ·{" "}
                    {t.last_used_at ? (
                      <>
                        last used{" "}
                        <time dateTime={t.last_used_at} title={formatDateTime(t.last_used_at)}>
                          {timeAgo(t.last_used_at)}
                        </time>
                      </>
                    ) : (
                      "never used"
                    )}
                  </p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setRevoking(t)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-4 text-sm text-ink-soft">
            No tokens yet. Create one, then add Dealflow to Claude with the command it shows you.
          </p>
        )}
      </Card>

      <NewTokenDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(t) => {
          setCreating(false)
          setCreated(t)
        }}
      />
      <TokenCreatedDialog token={created} onClose={() => setCreated(null)} />
      <ConfirmDialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        onConfirm={() =>
          revoking &&
          revoke.mutate({ path: { token_id: revoking.id } }, { onSettled: () => setRevoking(null) })
        }
        busy={revoke.isPending}
        title={`Revoke “${revoking?.name ?? ""}”?`}
        description="Anything using this token stops working straight away. Suggestions it already made stay in your inbox."
        confirmLabel="Revoke token"
      />
    </Section>
  )
}

function NewTokenDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (t: ApiTokenCreated) => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("Claude Code")
  const [error, setError] = useState<string | null>(null)
  const create = useMutation({
    ...tokensCreateTokenMutation(),
    onSuccess: (t) => {
      invalidate(queryClient, "tokensListTokens")
      setName("Claude Code")
      onCreated(t)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Create a token"
      description="Name it after where you'll use it, so you know which one to revoke later."
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          create.mutate({ body: { name: name.trim() } })
        }}
      >
        <Field label="Name" htmlFor="token-name">
          <Input
            id="token-name"
            required
            maxLength={100}
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            Create token
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  )
}

function TokenCreatedDialog({
  token,
  onClose,
}: {
  token: ApiTokenCreated | null
  onClose: () => void
}) {
  const command = token
    ? `claude mcp add --transport http dealflow ${mcpUrl()} --header "Authorization: Bearer ${token.token}"`
    : ""
  return (
    <Dialog
      open={token !== null}
      onClose={onClose}
      title="Your new token"
      description="Copy it now: Dealflow keeps only a fingerprint, so it can't show it again."
      className="max-w-xl"
    >
      {token && (
        <div className="space-y-4">
          <CopyBlock label="Token" value={token.token} />
          <CopyBlock label="Add Dealflow to Claude Code" value={command} />
          <div className="text-sm text-ink-soft">
            <p>
              For other MCP clients: the server is at{" "}
              <span className="font-mono text-ink">{mcpUrl()}</span> (Streamable HTTP), with the
              header <span className="font-mono text-ink">Authorization: Bearer</span> and the
              token.
            </p>
            <p className="mt-2 flex items-center gap-2">
              <Badge>Tip</Badge> Treat it like a password. Anyone with it can read what you can.
            </p>
          </div>
          <DialogFooter>
            <Button onClick={onClose}>Done</Button>
          </DialogFooter>
        </div>
      )}
    </Dialog>
  )
}
