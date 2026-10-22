import { NavLink } from "react-router"

import { cn } from "@/lib/utils"

const TABS = [
  { to: "/admin/users", label: "Users" },
  { to: "/admin/entities", label: "Legal entities" },
  { to: "/admin/governance", label: "Governance" },
  { to: "/admin/data-sources", label: "Data sources" },
  { to: "/admin/ai-monitoring", label: "Monitoring" },
]

export function AdminTabs() {
  return (
    <nav aria-label="Admin settings" className="mb-6 flex gap-1 border-b">
      {TABS.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              "-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              isActive ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
            )
          }
        >
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
