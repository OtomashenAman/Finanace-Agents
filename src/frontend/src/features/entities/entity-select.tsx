import type * as React from "react"

import { cn } from "@/lib/utils"

import { entityLabel, type LegalEntity } from "./api"

interface EntitySelectProps extends Omit<React.ComponentProps<"select">, "value" | "onChange"> {
  entities: LegalEntity[]
  value: string | null
  onChange: (entityId: string | null) => void
  /** Label of the empty option, e.g. "All entities"; omit to require a choice */
  allLabel?: string
}

export function EntitySelect({ entities, value, onChange, allLabel, className, ...props }: EntitySelectProps) {
  return (
    <select
      className={cn(
        "flex h-10 rounded-md border border-input bg-background px-3 text-sm",
        "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none",
        className,
      )}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      {...props}
    >
      {allLabel !== undefined ? <option value="">{allLabel}</option> : <option value="" disabled>Choose entity…</option>}
      {entities.map((e) => (
        <option key={e.id} value={e.id}>
          {entityLabel(e)}
          {e.is_active ? "" : " (inactive)"}
        </option>
      ))}
    </select>
  )
}
