import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Switch } from "@/components/ui/switch"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { errorMessage } from "@/lib/api"

import { useOrgSettings, useSetOrgSettings } from "../hooks"

export function MakerCheckerCard() {
  const { data, isPending, isError } = useOrgSettings()
  const save = useSetOrgSettings()

  const toggle = (allow: boolean) =>
    save.mutate(allow, {
      onSuccess: () =>
        toast.success(
          allow ? "Finance Admins may approve their own runs" : "Maker-checker enforced: nobody approves their own run",
        ),
      onError: (error) => toast.error(errorMessage(error, "Couldn't change the setting")),
    })

  return (
    <Panel title="Maker-checker">
      {isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
      {isError && <Alert>Couldn't load the setting.</Alert>}
      {data && (
        <div className="space-y-3">
          <label className="flex items-start gap-3">
            <Switch
              checked={data.allow_admin_self_approval}
              onCheckedChange={toggle}
              disabled={save.isPending}
              aria-label="Allow Finance Admins to approve their own runs"
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium">Allow Finance Admins to approve their own runs</span>
              <span className="block text-sm text-muted-foreground">
                {data.allow_admin_self_approval
                  ? "On: an admin can approve a run they prepared (recorded as a self-review in the audit trail)."
                  : "Off: every run needs an approver other than its preparer. With one Finance Admin, their own runs wait for a second admin."}
              </span>
            </span>
          </label>
          {data.updated_at && <p className="text-xs text-muted-foreground">Last changed {formatDateTime(data.updated_at)}</p>}
        </div>
      )}
    </Panel>
  )
}
