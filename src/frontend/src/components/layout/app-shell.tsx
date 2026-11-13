import { useState } from "react"
import { NavLink, Outlet } from "react-router"
import {
  CircleCheck,
  Database,
  History,
  LayoutDashboard,
  LayoutGrid,
  ListTodo,
  Workflow,
  Menu,
  Settings,
  ShoppingCart,
  X,
  type LucideIcon,
} from "lucide-react"

import type { Area } from "@/features/auth/api"
import { useCurrentUser } from "@/features/auth/hooks"
import { canUse, isAdmin } from "@/features/auth/roles"
import { useWorklist } from "@/features/worklist/hooks"
import { cn } from "@/lib/utils"

interface NavItem {
  label: string
  icon: LucideIcon
  to?: string // undefined = not built yet
  adminOnly?: boolean
  area?: Area // shown only to people given this area
}

const NAV: NavItem[] = [
  { label: "Overview", icon: LayoutDashboard, to: "/overview" },
  { label: "Agent Catalog", icon: LayoutGrid, to: "/catalog", area: "agent_catalog" },
  { label: "Service POD", icon: Workflow, to: "/pod", area: "service_pod" },
  { label: "Finance POD", icon: ShoppingCart, to: "/finance-pod", area: "finance_pod" },
  { label: "My Worklist", icon: ListTodo, to: "/worklist" },
  { label: "Approvals", icon: CircleCheck, to: "/approvals" },
  { label: "Audit Trail", icon: History, to: "/audit" },
  { label: "Data Sources", icon: Database, to: "/data-sources" },
  { label: "Admin Settings", icon: Settings, to: "/admin", adminOnly: true },
]

function Brand() {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-xl font-extrabold tracking-wider text-sky-400">◈</span>
        <span className="text-lg font-bold tracking-wider text-white">FINANCE AI</span>
      </div>
      <p className="mt-0.5 text-xs font-medium tracking-wide text-brand-ice/80">Autonomous Command Center</p>
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
        <span className="relative flex size-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
        </span>
        5 Workflows Active
      </div>
    </div>
  )
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { data: user } = useCurrentUser()
  const items = NAV.filter(
    (item) => (!item.adminOnly || isAdmin(user)) && (!item.area || canUse(user, item.area)),
  )
  const worklist = useWorklist()
  const todo = worklist.data?.action.length ?? 0
  const base = "relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150"
  return (
    <nav aria-label="Main" className="space-y-0.5">
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
                  ? "bg-white/12 font-semibold text-white shadow-2xs before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-1 before:rounded-r-full before:bg-sky-400"
                  : "text-brand-ice/75 hover:bg-white/6 hover:text-white hover:translate-x-0.5",
              )
            }
          >
            <Icon className="size-4" aria-hidden />
            {label}
            {to === "/worklist" && todo > 0 && (
              <span
                className="ml-auto rounded-full bg-white px-2 py-0.2 text-[11px] font-semibold text-brand-navy"
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

function UserDock() {
  const { data: user } = useCurrentUser()
  const name = user?.full_name ?? "Finance Admin"
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()

  return (
    <div className="mt-auto border-t border-white/10 pt-2.5">
      <div className="flex items-center gap-2.5 rounded-lg bg-white/5 p-2 text-xs">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-tr from-sky-500 to-indigo-600 font-bold text-white shadow-2xs">
          {initials || "FA"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-white">{name}</p>
          <p className="truncate text-[11px] text-brand-ice/70">
            {user?.role === "finance_admin" ? "Finance Admin" : "User"} · Demo
          </p>
        </div>
      </div>
      <p className="mt-1.5 text-center text-[10px] tracking-wider text-brand-ice/50 uppercase">
        Read-Only QuickBooks Safe
      </p>
    </div>
  )
}

const FOOTER = "DEMO TENANT | v1.0"

/** Signed-in layout: sidebar + routed page. Pages render their own header via <AppPage>. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-svh bg-brand-page md:pl-[234px]">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-[234px] flex-col bg-brand-navy px-3 pt-5 pb-3 md:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-4 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <Nav />
        </div>
        <UserDock />
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
