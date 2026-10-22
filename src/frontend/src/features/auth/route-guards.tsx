import { Navigate, Outlet, useLocation } from "react-router"

import { FullPageError, FullPageSpinner } from "@/components/full-page-status"

import { useCurrentUser } from "./hooks"
import { isAdmin } from "./roles"

/** Only allow same-app paths as post-login targets (no open redirects). */
function safeRedirect(target: unknown): string {
  return typeof target === "string" && target.startsWith("/") && !target.startsWith("//") ? target : "/"
}

/** Routes for signed-in users; everyone else is sent to /login (remembering where they were). */
export function RequireAuth() {
  const { data: user, isPending, isError, refetch } = useCurrentUser()
  const location = useLocation()

  if (isPending) return <FullPageSpinner />
  if (isError) return <FullPageError message="We couldn't check your session." onRetry={() => void refetch()} />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Outlet />
}

/** Routes for signed-out users (login); signed-in users go back to where they came from. */
export function GuestOnly() {
  const { data: user, isPending } = useCurrentUser()
  const location = useLocation()

  if (isPending) return <FullPageSpinner />
  if (user) {
    const from = (location.state as { from?: unknown } | null)?.from
    return <Navigate to={safeRedirect(from)} replace />
  }
  return <Outlet />
}

/** Finance Admin-only routes (nested inside <RequireAuth>); others go back to the overview. */
export function RequireAdmin() {
  const { data: user } = useCurrentUser()
  if (!isAdmin(user)) return <Navigate to="/overview" replace />
  return <Outlet />
}
