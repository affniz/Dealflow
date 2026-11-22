import { useQuery, useQueryClient } from "@tanstack/react-query"
import { type ReactNode, useCallback, useEffect, useMemo } from "react"

import { usersReadMeOptions } from "@/client/@tanstack/react-query.gen"
import { loginLogin, loginLogout } from "@/client/sdk.gen"
import { AuthContext, type AuthContextValue, onSessionExpired } from "@/lib/auth"

const ME_KEY = usersReadMeOptions().queryKey
const isMe = (key: readonly unknown[]) => (key[0] as { _id?: string })?._id === ME_KEY[0]._id

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  // the session lives in an httpOnly cookie, so ask the API who (if anyone) is signed in
  const me = useQuery({ ...usersReadMeOptions(), retry: false, staleTime: Infinity })

  const signedOut = useCallback(() => {
    // drop everything the last person could see, then ask again (the answer: nobody)
    queryClient.removeQueries({ predicate: (q) => !isMe(q.queryKey) })
    void queryClient.resetQueries({ queryKey: ME_KEY })
  }, [queryClient])

  useEffect(() => onSessionExpired(signedOut), [signedOut])

  const login = useCallback(
    async (email: string, password: string) => {
      const { error } = await loginLogin({ body: { username: email, password } })
      if (error) {
        const detail = (error as { detail?: unknown } | undefined)?.detail
        throw new Error(typeof detail === "string" ? detail : "Could not sign in")
      }
      queryClient.removeQueries({ predicate: (q) => !isMe(q.queryKey) })
      await queryClient.resetQueries({ queryKey: ME_KEY })
    },
    [queryClient],
  )

  const logout = useCallback(async () => {
    await loginLogout()
    signedOut()
  }, [signedOut])

  const value = useMemo<AuthContextValue>(
    () => ({
      user: me.data,
      isLoading: me.isPending,
      isAuthenticated: Boolean(me.data),
      login,
      logout,
    }),
    [me.data, me.isPending, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
