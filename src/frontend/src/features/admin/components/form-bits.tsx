import type * as React from "react"
import type { ReactNode } from "react"

import { Label } from "@/components/ui/label"
import type { UserRole } from "@/features/auth/api"
import { ROLE_LABELS } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

interface FieldProps {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}

/** Label + control + hint/error, with the ids the control's aria-describedby points at. */
export function Field({ id, label, error, hint, children }: FieldProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  )
}

export function RoleSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "flex h-11 w-full rounded-md border border-input bg-background px-3 text-[15px] text-foreground",
        "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {(Object.keys(ROLE_LABELS) as UserRole[]).map((role) => (
        <option key={role} value={role}>
          {ROLE_LABELS[role]}
        </option>
      ))}
    </select>
  )
}
