import { useState } from "react"
import { NavLink, Outlet } from "react-router"
import {
  Database,
  FileSignature,
  FileStack,
  FolderKanban,
  History,
  Inbox,
  LayoutDashboard,
  ListTodo,
  Menu,
  Settings,
  X,
  type LucideIcon,
} from "lucide-react"

import type { Area } from "@/features/auth/api"
import { useCurrentUser } from "@/features/auth/hooks"
import { canUse, isAdmin, ROLE_LABELS } from "@/features/auth/roles"
import { useAwaitingMe } from "@/features/esign/hooks"
import { useMyQueue } from "@/features/service-pod/hooks"
import { useWorklist } from "@/features/worklist/hooks"
import { cn } from "@/lib/utils"

interface NavItem {
  label: string
  icon: LucideIcon
  to: string
  adminOnly?: boolean
  area?: Area // shown only to people given this area
  /** Active only on this exact path (the dashboard, not every /pod page under it) */
  end?: boolean
  badge?: "queue" | "worklist" | "esign"
}

interface NavGroup {
  label?: string
  items: NavItem[]
}

// Hidden for now: the app is aligned on the Service POD. Overview, Approvals, Agent Catalog
// and Finance POD report on other parts of the app. To bring them back, add them here again
// (and set CATALOG_AND_FINANCE_POD_ENABLED in features/auth/roles.ts):
//   { label: "Overview", icon: LayoutDashboard, to: "/overview" },
//   { label: "Agent Catalog", icon: LayoutGrid, to: "/catalog", area: "agent_catalog" },
//   { label: "Finance POD", icon: ShoppingCart, to: "/finance-pod", area: "finance_pod" },
//   { label: "Approvals", icon: CircleCheck, to: "/approvals" },
const NAV: NavGroup[] = [
  {
    items: [
      {
        label: "Dashboard",
        icon: LayoutDashboard,
        to: "/pod",
        area: "service_pod",
        end: true,
      },
    ],
  },
  {
    label: "Service POD",
    items: [
      {
        label: "Cases",
        icon: FolderKanban,
        to: "/pod/cases",
        area: "service_pod",
      },
      {
        label: "My Queue",
        icon: Inbox,
        to: "/pod/queue",
        area: "service_pod",
        badge: "queue",
      },
      {
        label: "Snapshots",
        icon: FileStack,
        to: "/pod/sources",
        area: "service_pod",
      },
    ],
  },
  {
    label: "Workspace",
    items: [
      {
        label: "My Worklist",
        icon: ListTodo,
        to: "/worklist",
        badge: "worklist",
      },
      { label: "E-Signature", icon: FileSignature, to: "/esign", badge: "esign" },
      { label: "Audit Trail", icon: History, to: "/audit" },
      // QuickBooks connections and uploads: the Finance Admin's. Everyone else works on the
      // shared snapshots, refreshed from the admin's connection every night
      { label: "Data Sources", icon: Database, to: "/data-sources", adminOnly: true },
    ],
  },
  {
    label: "Admin",
    items: [{ label: "Settings", icon: Settings, to: "/admin", adminOnly: true }],
  },
]

function Brand() {
  const { data: user } = useCurrentUser()
  const count = user?.pod_workflows?.length ?? 0
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-xl font-extrabold tracking-wider text-sky-400">◈</span>
        <span className="text-lg font-bold tracking-wider text-white">FINANCE AI</span>
      </div>
      <p className="mt-0.5 text-xs font-medium tracking-wide text-brand-ice/80">Autonomous Command Center</p>
      {count > 0 && (
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          {count} Workflow{count === 1 ? "" : "s"} Active
        </div>
      )}
    </div>
  )
}

function CountBadge({ count, what }: { count: number; what: string }) {
  if (count <= 0) return null
  return (
    <span
      className="ml-auto min-w-5 rounded-full bg-white px-1.5 text-center text-[11px] leading-5 font-semibold text-brand-navy"
      aria-label={`${count} ${what}`}
    >
      {count}
    </span>
  )
}

/** Only mounted for people with the Service POD (its queries are refused for others) */
function QueueBadge() {
  const { count } = useMyQueue()
  return <CountBadge count={count} what={`item${count === 1 ? "" : "s"} in your queue`} />
}

function WorklistBadge() {
  const count = useWorklist().data?.action.length ?? 0
  return <CountBadge count={count} what={`item${count === 1 ? "" : "s"} need you`} />
}

/** Documents waiting for my countersignature */
function EsignBadge() {
  const count = useAwaitingMe() ?? 0
  return <CountBadge count={count} what={`document${count === 1 ? "" : "s"} to countersign`} />
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { data: user } = useCurrentUser()
  const groups = NAV.map((group) => ({
    ...group,
    items: group.items.filter((item) => (!item.adminOnly || isAdmin(user)) && (!item.area || canUse(user, item.area))),
  })).filter((group) => group.items.length > 0)

  return (
    <nav aria-label="Main" className="space-y-4">
      {groups.map((group, index) => (
        <div key={group.label ?? index} className="space-y-0.5">
          {group.label && (
            <p className="px-3 pb-1 text-[10px] font-semibold tracking-[0.12em] text-brand-ice/45 uppercase">
              {group.label}
            </p>
          )}
          {group.items.map(({ label, icon: Icon, to, end, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  "relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150",
                  "focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none",
                  isActive
                    ? "bg-white/12 font-semibold text-white before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:w-1 before:rounded-r-full before:bg-sky-400"
                    : "text-brand-ice/75 hover:bg-white/6 hover:text-white",
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="truncate">{label}</span>
              {badge === "queue" && <QueueBadge />}
              {badge === "worklist" && <WorklistBadge />}
              {badge === "esign" && <EsignBadge />}
            </NavLink>
          ))}
        </div>
      ))}
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
          <p className="truncate text-[11px] text-brand-ice/70">{user ? ROLE_LABELS[user.role] : ""}</p>
        </div>
      </div>
      <p className="mt-1.5 text-center text-[10px] tracking-wider text-brand-ice/50 uppercase">
        Read-Only QuickBooks Safe
      </p>
    </div>
  )
}

const FOOTER = "Read-only QuickBooks · v1.0"

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
          <p className="text-lg font-bold tracking-wide text-white">
            <span className="text-sky-400">◈</span> FINANCE AI
          </p>
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
