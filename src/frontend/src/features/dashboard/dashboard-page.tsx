import { LogOut } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCurrentUser, useLogout } from "@/features/auth/hooks"
import { initials, ROLE_LABELS } from "@/features/auth/roles"

/** Placeholder until the Finance Operations Overview is built. */
export function DashboardPage() {
  const { data: user } = useCurrentUser()
  const logout = useLogout()
  if (!user) return null

  return (
    <div className="min-h-svh bg-brand-page">
      <header className="flex items-center justify-between gap-4 bg-card px-6 py-5 sm:px-8">
        <h1 className="text-xl font-bold text-brand-navy sm:text-2xl">Finance Operations Overview</h1>
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-full bg-secondary text-sm font-semibold text-brand-navy">
            {initials(user)}
          </span>
          <span className="hidden text-sm font-medium sm:inline">{ROLE_LABELS[user.role]}</span>
          <Button variant="outline" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
            <LogOut aria-hidden />
            Sign out
          </Button>
        </div>
      </header>

      <main className="p-6 sm:p-8">
        <div className="max-w-xl rounded-lg border bg-card p-6">
          <p className="text-sm text-muted-foreground">Signed in as</p>
          <p className="mt-1 text-lg font-semibold">{user.full_name}</p>
          <p className="text-sm text-muted-foreground">{user.email}</p>
        </div>
      </main>
    </div>
  )
}
