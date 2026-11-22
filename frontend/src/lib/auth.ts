import { createContext, useContext } from "react"

import { client } from "@/client/client.gen"
import type { UserPublic } from "@/client/types.gen"
import { writeStorage } from "@/lib/storage"

// sign-ins used to be kept in localStorage; remove what an older version left there
writeStorage("dealflow.token", null)

// Signing in sets an httpOnly session cookie, which the browser sends with every API call and
// page scripts can't read. Calls that change something also send this header: the API refuses
// them without it, and another site can't add it.
client.setConfig({ baseUrl: "", headers: { "X-Dealflow-CSRF": "1" } })

const expiredListeners = new Set<() => void>()

/** Notified when an API call finds the session has ended (expired, or signed out elsewhere). */
export function onSessionExpired(listener: () => void) {
  expiredListeners.add(listener)
  return () => {
    expiredListeners.delete(listener)
  }
}

client.interceptors.response.use((response) => {
  // /users/me answers "who's signed in?" itself, and a failed sign-in isn't an expiry
  const own = ["/login/access-token", "/users/me"].some((path) => response.url.endsWith(path))
  if (response.status === 401 && !own) expiredListeners.forEach((l) => l())
  return response
})

export type AuthContextValue = {
  user: UserPublic | undefined
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}

/** Mirrors the backend roles: viewers are read-only; owners and admins manage settings. */
export function permissions(user: UserPublic | undefined) {
  const role = user?.role ?? "viewer"
  return {
    canWrite: role !== "viewer",
    isAdmin: role === "owner" || role === "admin",
    seesTeam: role !== "agent",
  }
}
