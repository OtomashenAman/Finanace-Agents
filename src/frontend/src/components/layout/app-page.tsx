import type { ReactNode } from "react"
import { LogOut, UserPlus } from "lucide-react"
import { toast } from "sonner"

import { useCurrentUser, useLogout, useSwitchAccount } from "@/features/auth/hooks"
import { initials, ROLE_LABELS } from "@/features/auth/roles"

interface AppPageProps {
  title: string
  /** Short guidance line under the header */
  subtitle?: string
  children: ReactNode
}

function comingSoon(feature: string) {
  toast.info(`${feature} is coming soon`)
}

function UserMenu() {
  const { data: user } = useCurrentUser()
  const logout = useLogout()
  const switchAccount = useSwitchAccount()
  if (!user) return null

  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className="flex size-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-brand-navy"
        aria-hidden
      >
        {initials(user)}
      </span>
      <span className="hidden font-medium text-brand-navy lg:inline" title={user.email}>
        {ROLE_LABELS[user.role]}
      </span>
      <button
        type="button"
        onClick={switchAccount}
        className="ml-1 rounded-md p-2 text-muted-foreground hover:bg-secondary hover:text-foreground"
        aria-label="Use another account in this tab"
        title="Use another account in this tab (others stay signed in)"
      >
        <UserPlus className="size-4" />
      </button>
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="ml-1 rounded-md p-2 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  )
}

/** Page frame inside the AppShell: header (title + tools + user), subtitle, content. */
export function AppPage({ title, subtitle, children }: AppPageProps) {
  return (
    <>
      <header className="flex items-center justify-between gap-4 bg-card px-5 py-4 sm:px-8 md:py-5">
        <h1 className="min-w-0 text-lg leading-tight font-bold text-brand-navy sm:text-[1.6rem]">{title}</h1>
        <div className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
          <button type="button" className="hidden px-2 py-1 hover:text-foreground sm:inline" onClick={() => comingSoon("Search")}>
            Search
          </button>
          <span className="hidden sm:inline" aria-hidden>
            |
          </span>
          <button type="button" className="hidden px-2 py-1 hover:text-foreground sm:inline" onClick={() => comingSoon("Help")}>
            Help
          </button>
          <span className="hidden sm:inline" aria-hidden>
            |
          </span>
          <UserMenu />
        </div>
      </header>
      {subtitle && (
        <p className="border-b border-border px-5 py-3 text-sm text-muted-foreground sm:px-8">{subtitle}</p>
      )}
      <main className="px-5 py-5 sm:px-8 sm:py-6">{children}</main>
    </>
  )
}
