import { useState } from "react"
import { Link, NavLink, Outlet } from "react-router"
import { ArrowLeft, LayoutDashboard, Menu, X, type LucideIcon } from "lucide-react"

import { useCurrentUser } from "@/features/auth/hooks"
import { cn } from "@/lib/utils"

import type { Overview } from "../api"
import { useOverview } from "../hooks"
import { AREAS, GENERAL, type Page } from "../registry"

const OVERVIEW: Page = { to: "/finance-pod", label: "Overview", icon: LayoutDashboard, end: true }

function Brand() {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 text-base font-extrabold text-white shadow-sm">
          ₣
        </span>
        <div>
          <p className="text-[15px] leading-tight font-bold tracking-wider text-white">FINANCE POD</p>
          <p className="text-[11px] font-medium text-teal-200/75">Payables & receivables agents</p>
        </div>
      </div>
    </div>
  )
}

/** Leaves the Finance POD for the main Finance AI application. */
function BackToApp({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      to="/overview"
      onClick={onNavigate}
      className="flex items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm font-medium text-teal-50 transition-colors hover:bg-white/12 hover:text-white"
    >
      <ArrowLeft className="size-4" aria-hidden /> Back to Finance AI
    </Link>
  )
}

function Item({ page, overview, onNavigate }: { page: Page; overview: Overview | undefined; onNavigate?: () => void }) {
  const Icon: LucideIcon = page.icon
  const n = overview && page.count ? page.count(overview) : 0
  return (
    <NavLink
      to={page.to}
      end={page.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "relative flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
          isActive
            ? "bg-white/12 font-semibold text-white before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:w-1 before:rounded-r-full before:bg-emerald-400"
            : "text-teal-100/75 hover:bg-white/6 hover:text-white",
        )
      }
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span className="truncate">{page.label}</span>
      {n > 0 && (
        <span className="ml-auto rounded-full bg-amber-300 px-1.5 text-[11px] font-semibold text-amber-950 tabular-nums">{n}</span>
      )}
    </NavLink>
  )
}

/** The Finance POD's navigation, grouped by area; built from the registry. */
function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const overview = useOverview().data
  return (
    <nav aria-label="Finance POD" className="space-y-4">
      <Item page={OVERVIEW} overview={overview} onNavigate={onNavigate} />
      {AREAS.map((area) => {
        const AreaIcon = area.icon
        return (
          <div key={area.key}>
            <p className="mb-1 flex items-center gap-1.5 px-3 text-[11px] font-semibold tracking-wider text-teal-200/55 uppercase">
              <AreaIcon className="size-3.5" aria-hidden /> {area.name}
            </p>
            <div className="space-y-0.5">
              {area.pages.map((p) => (
                <Item key={p.to} page={p} overview={overview} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        )
      })}
      <div className="space-y-0.5 border-t border-white/10 pt-3">
        {GENERAL.map((p) => (
          <Item key={p.to} page={p} overview={overview} onNavigate={onNavigate} />
        ))}
      </div>
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
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-tr from-emerald-500 to-teal-600 font-bold text-white">
          {initials || "FA"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-white">{name}</p>
          <p className="truncate text-[11px] text-teal-200/70">Finance POD · Demo</p>
        </div>
      </div>
    </div>
  )
}

/** The Finance POD as an application of its own: its own sidebar (no Finance AI sidebar),
 *  and a way back to Finance AI. */
export function FpodShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const close = () => setMenuOpen(false)
  return (
    <div className="min-h-svh bg-brand-page md:pl-[240px]">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-[240px] flex-col bg-gradient-to-b from-[#0b2f2c] to-[#0a2320] px-3 pt-5 pb-3 md:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-4 px-0.5">
          <BackToApp />
        </div>
        <div className="mt-4 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <Nav />
        </div>
        <UserDock />
      </aside>

      {/* Mobile top bar + slide-down menu */}
      <div className="sticky top-0 z-30 bg-[#0b2f2c] md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="rounded-md p-2 text-teal-50 hover:bg-white/10"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
        {menuOpen && (
          <div className="max-h-[75svh] space-y-4 overflow-y-auto border-t border-white/10 px-3 pt-3 pb-4">
            <BackToApp onNavigate={close} />
            <Nav onNavigate={close} />
          </div>
        )}
      </div>

      <Outlet />
    </div>
  )
}
