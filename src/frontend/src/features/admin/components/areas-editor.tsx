import type { Area, UserRole } from "@/features/auth/api"
import { AREAS } from "@/features/auth/roles"

interface AreasEditorProps {
  role: UserRole
  value: Area[]
  onChange: (value: Area[]) => void
  disabled?: boolean
}

/** The parts of the app shown to a person; the PODs only for a Finance Admin. */
export function AreasEditor({ role, value, onChange, disabled }: AreasEditorProps) {
  const toggle = (area: Area, on: boolean) =>
    onChange(AREAS.map((a) => a.value).filter((a) => (a === area ? on : value.includes(a))))

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="sr-only">Areas</legend>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {AREAS.map(({ value: area, label, adminOnly }) => {
          const allowed = !adminOnly || role === "finance_admin"
          return (
            <label
              key={area}
              className={`flex items-center gap-2 text-sm ${allowed ? "" : "text-muted-foreground"}`}
            >
              <input
                type="checkbox"
                className="size-4 accent-brand-navy"
                checked={allowed && value.includes(area)}
                disabled={!allowed}
                onChange={(e) => toggle(area, e.target.checked)}
              />
              {label}
            </label>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {role === "finance_admin"
          ? "Only the ticked areas appear in their menu. Finance POD approvals go only to Finance Admins with Finance POD."
          : "Service POD and Finance POD are for Finance Admins only."}
      </p>
    </fieldset>
  )
}
