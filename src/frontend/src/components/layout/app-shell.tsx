import { useState } from "react"
import { NavLink, Outlet } from "react-router"
import {
  CircleCheck,
  Database,
  History,
  LayoutDashboard,
  LayoutGrid,
  ListTodo,
  Menu,
  Settings,
  X,
  type LucideIcon,
} from "lucide-react"

import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { useWorklist } from "@/features/worklist/hooks"
import { cn } from "@/lib/utils"

interface NavItem {
  label: string
  icon: LucideIcon
  to?: string // undefined = not built yet
  adminOnly?: boolean
}

const NAV: NavItem[] = [
  { label: "Overview", icon: LayoutDashboard, to: "/overview" },
  { label: "Agent Catalog", icon: LayoutGrid, to: "/catalog" },
  { label: "My Worklist", icon: ListTodo, to: "/worklist" },
  { label: "Approvals", icon: CircleCheck, to: "/approvals" },
  { label: "Audit Trail", icon: History, to: "/audit" },
  { label: "Data Sources", icon: Database, to: "/data-sources" },
  { label: "Admin Settings", icon: Settings, to: "/admin", adminOnly: true },
]

function Brand() {
  return (
    <div>
      <p className="text-xl font-bold tracking-wide text-brand-navy-muted">◈ FINANCE AI</p>
      <p className="mt-3 text-[15px] text-brand-ice">Command Center</p>
    </div>
  )
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { data: user } = useCurrentUser()
  const items = NAV.filter((item) => !item.adminOnly || isAdmin(user))
  const worklist = useWorklist()
  const todo = worklist.data?.action.length ?? 0
  const base = "flex items-center gap-3 rounded-lg px-4 py-3 text-[15px] transition-colors"
  return (
    <nav aria-label="Main" className="space-y-1.5">
      {items.map(({ label, icon: Icon, to }) =>
        to ? (
          <NavLink
            key={label}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                base,
                isActive
                  ? "bg-white/10 font-semibold text-white"
                  : "text-brand-ice/80 hover:bg-white/5 hover:text-white",
              )
            }
          >
            <Icon className="size-4" aria-hidden />
            {label}
            {to === "/worklist" && todo > 0 && (
              <span
                className="ml-auto rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-brand-navy"
                aria-label={`${todo} item${todo === 1 ? "" : "s"} need you`}
              >
                {todo}
              </span>
            )}
          </NavLink>
        ) : (
          <span
            key={label}
            aria-disabled="true"
            title="Coming soon"
            className={cn(base, "cursor-not-allowed text-brand-ice/35")}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </span>
        ),
      )}
    </nav>
  )
}

const FOOTER = "DEMO TENANT | v1.0"

/** Signed-in layout: sidebar + routed page. Pages render their own header via <AppPage>. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-svh bg-brand-page md:pl-[234px]">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-[234px] flex-col bg-brand-navy px-3.5 pt-9 pb-6 md:flex">
        <div className="px-4">
          <Brand />
        </div>
        <div className="mt-10 flex-1 overflow-y-auto">
          <Nav />
        </div>
        <p className="px-4 text-[11px] tracking-wide text-brand-ice/60">{FOOTER}</p>
      </aside>

      {/* Mobile top bar + slide-down menu */}
      <div className="sticky top-0 z-30 bg-brand-navy md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <p className="text-lg font-bold tracking-wide text-brand-navy-muted">◈ FINANCE AI</p>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="rounded-md p-2 text-brand-ice hover:bg-white/10"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
        {menuOpen && (
          <div className="border-t border-white/10 px-3 pt-2 pb-4">
            <Nav onNavigate={() => setMenuOpen(false)} />
            <p className="mt-4 px-4 text-[11px] text-brand-ice/60">{FOOTER}</p>
          </div>
        )}
      </div>

      <Outlet />
    </div>
  )
}
