import { Navigate, Outlet, useLocation } from "react-router-dom"

import { Spinner } from "@/components/ui/card"
import { permissions, useAuth } from "@/lib/auth"

export function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner />
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

export function RequireAdmin() {
  const { user } = useAuth()
  return permissions(user).isAdmin ? <Outlet /> : <Navigate to="/" replace />
}
