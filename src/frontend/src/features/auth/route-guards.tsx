import { Navigate, Outlet, useLocation } from "react-router"

import { FullPageError, FullPageSpinner } from "@/components/full-page-status"

import type { Area } from "./api"
import { useCurrentUser } from "./hooks"
import { canUse, isAdmin } from "./roles"

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

/** Home: the Service POD for anyone with a workflow, otherwise their account page. */
export function HomeRedirect() {
  const { data: user } = useCurrentUser()
  return <Navigate to={canUse(user, "service_pod") ? "/pod" : "/account"} replace />
}

/** Finance Admin-only routes (nested inside <RequireAuth>); others go back home. */
export function RequireAdmin() {
  const { data: user } = useCurrentUser()
  if (!isAdmin(user)) return <Navigate to="/" replace />
  return <Outlet />
}

/** Routes of one area (nested inside <RequireAuth>); people without it go back home. */
export function RequireArea({ area }: { area: Area }) {
  const { data: user } = useCurrentUser()
  if (!canUse(user, area)) return <Navigate to="/" replace />
  return <Outlet />
}
