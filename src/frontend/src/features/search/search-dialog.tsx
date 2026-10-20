import { useEffect, useMemo, useState, type KeyboardEvent } from "react"
import { useNavigate } from "react-router"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import {
  Building2,
  FileText,
  LayoutGrid,
  LoaderCircle,
  Search,
  SquareArrowOutUpRight,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react"

import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

import { searchApi, type HitKind, type SearchHit } from "./api"

type Kind = HitKind | "page"

const ICONS: Record<Kind, LucideIcon> = {
  run: FileText,
  agent: LayoutGrid,
  user: UserRound,
  entity: Building2,
  page: SquareArrowOutUpRight,
}

const PAGES: { title: string; link: string; adminOnly?: boolean; words: string }[] = [
  { title: "Overview", link: "/overview", words: "dashboard kpi home" },
  { title: "Agent Catalog", link: "/catalog", words: "agents new run" },
  { title: "My Worklist", link: "/worklist", words: "todo tasks" },
  { title: "Approvals", link: "/approvals", words: "review approve" },
  { title: "Audit Trail", link: "/audit", words: "history log events" },
  { title: "Data Sources", link: "/data-sources", words: "quickbooks upload csv" },
  { title: "My account", link: "/account", words: "password profile" },
  { title: "Help", link: "/help", words: "guide how" },
  { title: "Users", link: "/admin/users", adminOnly: true, words: "admin people roles" },
  { title: "Legal entities", link: "/admin/entities", adminOnly: true, words: "companies" },
  { title: "Governance", link: "/admin/governance", adminOnly: true, words: "thresholds matrix delegation" },
  { title: "AI monitoring", link: "/admin/ai-monitoring", adminOnly: true, words: "llm queue jobs" },
]

type Row = { kind: Kind; title: string; subtitle: string | null; link: string }

function useDebounced(value: string, ms: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Ctrl/⌘ K or the header button: find a run, agent, page or (admins) person. */
export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Mounted only while open, so every opening starts empty
  return open ? <SearchPanel onClose={onClose} /> : null
}

function SearchPanel({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const { data: user } = useCurrentUser()
  const admin = isAdmin(user)
  const [query, setQuery] = useState("")
  const [selected, setActive] = useState(0)
  const term = useDebounced(query.trim(), 200)

  const results = useQuery({
    queryKey: ["search", term],
    queryFn: () => searchApi.search(term),
    enabled: term.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  })

  const rows = useMemo<Row[]>(() => {
    const q = query.trim().toLowerCase()
    const pages = PAGES.filter((p) => (admin || !p.adminOnly) && (!q || `${p.title} ${p.words}`.toLowerCase().includes(q)))
      .slice(0, q ? 4 : PAGES.length)
      .map((p) => ({ kind: "page" as const, title: p.title, subtitle: "Page", link: p.link }))
    const hits: Row[] = term.length >= 2 && results.data ? results.data.hits.map((h: SearchHit) => ({ ...h })) : []
    return [...hits, ...pages]
  }, [query, term, results.data, admin])

  const active = Math.min(selected, Math.max(rows.length - 1, 0))

  const go = (row: Row | undefined) => {
    if (!row) return
    onClose()
    void navigate(row.link)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") onClose()
    else if (e.key === "ArrowDown") {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, rows.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      go(rows[active])
    }
  }

  const searching = results.isFetching && term.length >= 2

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        className="w-full max-w-xl overflow-hidden rounded-lg border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2 border-b px-4">
          {searching ? (
            <LoaderCircle className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
          ) : (
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            autoFocus
            placeholder={admin ? "Run, invoice number, agent, person, entity…" : "Run, invoice number, agent or page…"}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            aria-label="Search"
            role="combobox"
            aria-expanded="true"
            aria-controls="search-results"
            aria-activedescendant={rows[active] ? `search-row-${active}` : undefined}
          />
          <button type="button" onClick={onClose} className="rounded p-1 text-muted-foreground hover:text-foreground" aria-label="Close search">
            <X className="size-4" />
          </button>
        </div>
        <ul id="search-results" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {rows.map((row, i) => {
            const Icon = ICONS[row.kind]
            return (
              <li
                key={`${row.kind}-${row.link}-${row.title}`}
                id={`search-row-${i}`}
                role="option"
                aria-selected={i === active}
                className={cn("flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm", i === active && "bg-secondary")}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(row)}
              >
                <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{row.title}</span>
                  {row.subtitle && <span className="block truncate text-xs text-muted-foreground">{row.subtitle}</span>}
                </span>
              </li>
            )
          })}
          {rows.length === 0 && (
            <li className="px-3 py-8 text-center text-sm text-muted-foreground">
              {searching ? "Searching…" : "Nothing matches. Try a run number like 1006 or an invoice number."}
            </li>
          )}
        </ul>
        <p className="border-t px-4 py-2 text-xs text-muted-foreground">↑ ↓ to move · Enter to open · Esc to close</p>
      </div>
    </div>
  )
}
