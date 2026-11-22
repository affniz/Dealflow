import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, Pencil, Plus } from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  configReadConfigOptions,
  usersCreateUserMutation,
  usersMakePasswordResetLinkMutation,
  usersListUsersOptions,
  usersUpdateUserMutation,
} from "@/client/@tanstack/react-query.gen"
import type { PasswordResetLink, Role, UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Badge, Card, Spinner } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm"
import { CopyBlock } from "@/components/ui/copy"
import { Dialog, DialogFooter } from "@/components/ui/dialog"
import { Field, Select } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Sheet, SheetFooter } from "@/components/ui/sheet"
import { apiErrorMessage, invalidate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useUnsavedChanges } from "@/lib/sheet"
import { useToast } from "@/lib/toast"
import { formatDateTime } from "@/lib/time"
import { cn, initials } from "@/lib/utils"

const QUERIES = ["usersListUsers", "usersUserDirectory"]

const ROLES: { value: Role; label: string; help: string }[] = [
  { value: "owner", label: "Owner", help: "Everything, including managing admins" },
  { value: "admin", label: "Admin", help: "All records, settings and people" },
  { value: "agent", label: "Agent", help: "Only their own contacts, companies and deals" },
  { value: "viewer", label: "Viewer", help: "Sees everything, changes nothing" },
]

/** A password to hand to a new person; they can change it after signing in. */
function generatePassword() {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
  const bytes = crypto.getRandomValues(new Uint8Array(14))
  return Array.from(bytes, (b) => chars[b % chars.length]).join("")
}

/** Who can sign in, and what they can do. */
export function TeamSettings() {
  const { user: me } = useAuth()
  const isOwner = me?.role === "owner"
  const queryClient = useQueryClient()
  const toast = useToast()
  const users = useQuery(usersListUsersOptions({ query: { limit: 500 } }))
  const [editing, setEditing] = useState<UserPublic | "new" | null>(null)
  const [deactivating, setDeactivating] = useState<UserPublic | null>(null)
  const [resetLink, setResetLink] = useState<{ who: string; link: PasswordResetLink } | null>(null)
  // the demo's visitors share its accounts and published password
  const config = useQuery({ ...configReadConfigOptions(), staleTime: Infinity })
  const makeResetLink = useMutation({
    ...usersMakePasswordResetLinkMutation(),
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const update = useMutation({
    ...usersUpdateUserMutation(),
    onSuccess: (u) => {
      invalidate(queryClient, ...QUERIES)
      toast(`Saved ${u.full_name || u.email}`)
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  // only an owner can make someone an owner, or change an owner
  const canManage = (u: UserPublic) => u.id !== me?.id && (isOwner || u.role !== "owner")
  const roleOptions = ROLES.filter((r) => isOwner || r.value !== "owner")
  const people = [...(users.data?.data ?? [])].sort(
    (a, b) => Number(b.is_active) - Number(a.is_active) || a.id - b.id,
  )

  return (
    <section aria-labelledby="team" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="team" className="text-base font-semibold">
            Team
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-soft">
            Who can sign in and what they can do. Deactivated people can't sign in; their records
            stay assigned to them until you reassign them.
          </p>
        </div>
        <Button variant="outline" onClick={() => setEditing("new")}>
          <Plus /> Add person
        </Button>
      </div>

      <Card>
        {users.isPending ? (
          <div className="p-4">
            <Spinner />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {people.map((u) => {
              const name = u.full_name || u.email
              const manageable = canManage(u)
              return (
                <li
                  key={u.id}
                  className={cn(
                    "flex flex-wrap items-center gap-3 px-4 py-3",
                    !u.is_active && "opacity-60",
                  )}
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-ink-soft">
                    {initials(name)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {name}
                      {u.id === me?.id && (
                        <span className="font-normal text-ink-faint"> (you)</span>
                      )}
                    </p>
                    <p className="truncate text-xs text-ink-soft">{u.email}</p>
                  </div>
                  {!u.is_active && <Badge>Deactivated</Badge>}
                  <Select
                    aria-label={`Role for ${name}`}
                    className="h-8 w-32"
                    value={u.role}
                    disabled={!manageable || update.isPending}
                    title={
                      u.id === me?.id
                        ? "You can't change your own role"
                        : manageable
                          ? ROLES.find((r) => r.value === u.role)?.help
                          : "Only an owner can change an owner"
                    }
                    onChange={(e) =>
                      update.mutate({
                        path: { user_id: u.id },
                        body: { role: e.target.value as Role },
                      })
                    }
                  >
                    {/* show the current role even if this admin couldn't pick it */}
                    {(manageable ? roleOptions : ROLES).map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </Select>
                  {manageable && u.is_active && config.data?.demo === false && (
                    <Button
                      variant="ghost"
                      size="sm"
                      title="A one-time link for them to choose a new password"
                      disabled={makeResetLink.isPending}
                      onClick={() =>
                        makeResetLink.mutate(
                          { path: { user_id: u.id } },
                          { onSuccess: (link) => setResetLink({ who: name, link }) },
                        )
                      }
                    >
                      <KeyRound /> Reset link
                    </Button>
                  )}
                  <div className="w-24 text-right">
                    {manageable && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          u.is_active
                            ? setDeactivating(u)
                            : update.mutate({ path: { user_id: u.id }, body: { is_active: true } })
                        }
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </Button>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label={`Edit ${name}`}
                    disabled={!manageable && u.id !== me?.id}
                    onClick={() => setEditing(u)}
                  >
                    <Pencil />
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
      <dl className="grid gap-x-6 gap-y-1 text-xs text-ink-soft sm:grid-cols-2">
        {ROLES.map((r) => (
          <div key={r.value} className="flex gap-1">
            <dt className="font-medium text-ink">{r.label}:</dt>
            <dd>{r.help}</dd>
          </div>
        ))}
      </dl>

      <PersonSheet
        open={editing !== null}
        person={editing === "new" || editing === null ? undefined : editing}
        roles={roleOptions}
        onClose={() => setEditing(null)}
      />
      <ConfirmDialog
        open={deactivating !== null}
        onClose={() => setDeactivating(null)}
        onConfirm={() =>
          deactivating &&
          update.mutate(
            { path: { user_id: deactivating.id }, body: { is_active: false } },
            { onSettled: () => setDeactivating(null) },
          )
        }
        busy={update.isPending}
        title={`Deactivate ${deactivating?.full_name || deactivating?.email}?`}
        description="They won't be able to sign in. Their contacts, companies, deals and activities stay assigned to them; you can reactivate them at any time."
        confirmLabel="Deactivate"
      />
      <Dialog
        open={resetLink !== null}
        onClose={() => setResetLink(null)}
        title={`Password reset link for ${resetLink?.who ?? ""}`}
        description="Send it to them yourself. It works once, until the time below; their current password keeps working until they use it. Copy it now: it can't be shown again."
      >
        {resetLink && (
          <div className="space-y-2">
            <CopyBlock
              label="Link"
              value={`${window.location.origin}/reset-password#${resetLink.link.token}`}
            />
            <p className="text-xs text-ink-soft">
              Expires {formatDateTime(resetLink.link.expires_at)}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button onClick={() => setResetLink(null)}>Done</Button>
        </DialogFooter>
      </Dialog>
    </section>
  )
}

function PersonSheet({
  open,
  person,
  roles,
  onClose,
}: {
  open: boolean
  person?: UserPublic
  roles: typeof ROLES
  onClose: () => void
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={person ? `Edit ${person.full_name || person.email}` : "Add person"}
      description={
        person ? undefined : "Give them the email and password below so they can sign in."
      }
    >
      <PersonForm key={`${open}-${person?.id}`} person={person} roles={roles} onClose={onClose} />
    </Sheet>
  )
}

function PersonForm({
  person,
  roles,
  onClose,
}: {
  person?: UserPublic
  roles: typeof ROLES
  onClose: () => void
}) {
  const { user: me } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const isSelf = person?.id === me?.id
  const [error, setError] = useState<string | null>(null)
  const [initial] = useState(() => ({
    full_name: person?.full_name ?? "",
    email: person?.email ?? "",
    role: (person?.role ?? "agent") as Role,
    password: person ? "" : generatePassword(),
  }))
  const [v, setV] = useState(initial)
  useUnsavedChanges(JSON.stringify(v) !== JSON.stringify(initial))
  const set = (patch: Partial<typeof v>) => setV({ ...v, ...patch })

  const done = (message: string) => {
    invalidate(queryClient, ...QUERIES)
    toast(message)
    onClose()
  }
  const onError = (e: unknown) => setError(apiErrorMessage(e))
  const create = useMutation({
    ...usersCreateUserMutation(),
    onSuccess: (u) => done(`Added ${u.full_name || u.email}`),
    onError,
  })
  const update = useMutation({
    ...usersUpdateUserMutation(),
    onSuccess: () => done("Saved"),
    onError,
  })
  const busy = create.isPending || update.isPending

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const full_name = v.full_name.trim() || null
    const email = v.email.trim()
    if (!person) {
      return create.mutate({ body: { full_name, email, role: v.role, password: v.password } })
    }
    const body = {
      ...(full_name !== (person.full_name ?? null) ? { full_name } : {}),
      ...(email.toLowerCase() !== person.email ? { email } : {}),
      ...(!isSelf && v.role !== person.role ? { role: v.role } : {}),
      ...(v.password ? { password: v.password } : {}),
    }
    if (Object.keys(body).length === 0) return onClose()
    update.mutate({ path: { user_id: person.id }, body })
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col space-y-4">
      <Field label="Name" htmlFor="person-name">
        <Input
          id="person-name"
          maxLength={255}
          autoFocus={!person}
          autoComplete="off"
          value={v.full_name}
          onChange={(e) => set({ full_name: e.target.value })}
        />
      </Field>
      <Field label="Email" htmlFor="person-email">
        <Input
          id="person-email"
          type="email"
          required
          maxLength={255}
          autoComplete="off"
          value={v.email}
          onChange={(e) => set({ email: e.target.value })}
        />
      </Field>
      {!isSelf && (
        <Field label="Role" htmlFor="person-role">
          <Select
            id="person-role"
            value={v.role}
            onChange={(e) => set({ role: e.target.value as Role })}
          >
            {roles.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}: {r.help}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field
        label={person ? "New password (leave empty to keep theirs)" : "Password"}
        htmlFor="person-password"
      >
        <div className="flex gap-2">
          <Input
            id="person-password"
            required={!person}
            minLength={8}
            maxLength={128}
            autoComplete="new-password"
            value={v.password}
            onChange={(e) => set({ password: e.target.value })}
            className="font-mono"
          />
          <Button variant="outline" onClick={() => set({ password: generatePassword() })}>
            Generate
          </Button>
        </div>
      </Field>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <SheetFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : person ? "Save" : "Add person"}
        </Button>
      </SheetFooter>
    </form>
  )
}
