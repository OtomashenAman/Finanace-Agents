import { useCallback, useEffect, useState, type ReactNode } from "react"
import { KeyRound, LogOut, Search, UserPlus } from "lucide-react"
import { Link } from "react-router"

import { useCurrentUser, useLogout, useSwitchAccount } from "@/features/auth/hooks"
import { initials, ROLE_LABELS } from "@/features/auth/roles"
import { SearchDialog } from "@/features/search/search-dialog"

interface AppPageProps {
  title: string
  /** Short guidance line under the header */
  subtitle?: string
  children: ReactNode
}

function useSearchShortcut(open: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        open()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])
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
      <Link
        to="/account"
        className="ml-1 rounded-md p-2 text-muted-foreground hover:bg-secondary hover:text-foreground"
        aria-label="My account and password"
        title="My account and password"
      >
        <KeyRound className="size-4" />
      </Link>
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
  const [searching, setSearching] = useState(false)
  const openSearch = useCallback(() => setSearching(true), [])
  useSearchShortcut(openSearch)
  return (
    <>
      <header className="flex items-center justify-between gap-4 bg-card px-5 py-4 sm:px-8 md:py-5">
        <h1 className="min-w-0 text-lg leading-tight font-bold text-brand-navy sm:text-[1.6rem]">{title}</h1>
        <div className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-md px-2 py-1 hover:text-foreground"
            onClick={openSearch}
            aria-label="Search (Ctrl K)"
            title="Search (Ctrl K / ⌘ K)"
          >
            <Search className="size-4 sm:hidden" aria-hidden />
            <span className="hidden sm:inline">Search</span>
          </button>
          <span className="hidden sm:inline" aria-hidden>
            |
          </span>
          <Link to="/help" className="hidden px-2 py-1 hover:text-foreground sm:inline">
            Help
          </Link>
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
      <SearchDialog open={searching} onClose={() => setSearching(false)} />
    </>
  )
}
