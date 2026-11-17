import { createContext, useContext } from "react"

import { client } from "@/client/client.gen"
import type { UserPublic } from "@/client/types.gen"
import { readStorage, writeStorage } from "@/lib/storage"

const TOKEN_KEY = "dealflow.token"
let token = readStorage(TOKEN_KEY)
const listeners = new Set<() => void>()

export function getToken() {
  return token
}

/** Notified whenever the token changes (sign in, sign out, expiry). */
export function onTokenChange(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function setToken(value: string | null) {
  token = value
  writeStorage(TOKEN_KEY, value)
  listeners.forEach((l) => l())
}

// Every generated API call sends the bearer token; a 401 means it expired, so log out.
client.setConfig({ baseUrl: "", auth: () => token ?? undefined })
client.interceptors.response.use((response) => {
  if (response.status === 401 && token && !response.url.endsWith("/login/access-token")) {
    setToken(null)
  }
  return response
})

export type AuthContextValue = {
  user: UserPublic | undefined
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
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
