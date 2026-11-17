import { useQuery, useQueryClient } from "@tanstack/react-query"
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react"

import { usersReadMeOptions } from "@/client/@tanstack/react-query.gen"
import { loginLogin } from "@/client/sdk.gen"
import { AuthContext, type AuthContextValue, getToken, onTokenChange, setToken } from "@/lib/auth"

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = useState(Boolean(getToken()))

  useEffect(
    () =>
      onTokenChange(() => {
        setHasToken(Boolean(getToken()))
        if (!getToken()) queryClient.clear()
      }),
    [queryClient],
  )

  const me = useQuery({ ...usersReadMeOptions(), enabled: hasToken, retry: false })

  const login = useCallback(
    async (email: string, password: string) => {
      const { data, error } = await loginLogin({ body: { username: email, password } })
      if (error || !data) {
        const detail = (error as { detail?: unknown } | undefined)?.detail
        throw new Error(typeof detail === "string" ? detail : "Could not sign in")
      }
      setToken(data.access_token)
      await queryClient.invalidateQueries({ queryKey: usersReadMeOptions().queryKey })
    },
    [queryClient],
  )

  const logout = useCallback(() => setToken(null), [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user: me.data,
      isLoading: hasToken && me.isPending,
      isAuthenticated: hasToken && Boolean(me.data),
      login,
      logout,
    }),
    [me.data, me.isPending, hasToken, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
