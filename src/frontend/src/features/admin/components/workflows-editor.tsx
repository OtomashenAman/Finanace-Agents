import type { PodWorkflow, UserRole } from "@/features/auth/api"
import { POD_WORKFLOWS, ROLE_LABELS, ROLE_WORKFLOWS } from "@/features/auth/roles"

interface WorkflowsEditorProps {
  role: UserRole
  value: PodWorkflow[]
  onChange: (value: PodWorkflow[]) => void
  disabled?: boolean
}

/** Service POD workflows a person works in. A role starts with its own; the admin adjusts. */
export function WorkflowsEditor({ role, value, onChange, disabled }: WorkflowsEditorProps) {
  if (role === "finance_admin") {
    return (
      <p className="text-sm text-muted-foreground">
        Finance Admins work in every Service POD workflow and give every sign-off.
      </p>
    )
  }

  const defaults = ROLE_WORKFLOWS[role]
  const toggle = (workflow: PodWorkflow, on: boolean) =>
    onChange(POD_WORKFLOWS.map((w) => w.value).filter((w) => (w === workflow ? on : value.includes(w))))

  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="sr-only">Service POD workflows</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {POD_WORKFLOWS.map(({ value: workflow, label }) => (
          <label key={workflow} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-brand-navy"
              checked={value.includes(workflow)}
              onChange={(e) => toggle(workflow, e.target.checked)}
            />
            {label}
            {defaults.includes(workflow) && (
              <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] text-muted-foreground">
                {ROLE_LABELS[role]} default
              </span>
            )}
          </label>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        They open and work cases, draft emails, upload documents and import sources in these workflows only. Approving,
        sending email, recording postings and removing sources stay with a Finance Admin.
        {value.length === 0 && " With no workflow ticked, the Service POD is hidden from them."}
      </p>
    </fieldset>
  )
}
