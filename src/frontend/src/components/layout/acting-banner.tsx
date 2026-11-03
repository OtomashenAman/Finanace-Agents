import { FlaskConical } from "lucide-react"

import { useCurrentUser, useLogout } from "@/features/auth/hooks"

/** In a tab a Finance Admin opened as another user (testing a workflow): who this tab is,
 *  and that everything done here is audited as the admin's. */
export function ActingBanner() {
  const { data: me } = useCurrentUser()
  const logout = useLogout()
  if (!me?.acted_by) return null
  const end = () => logout.mutate(undefined, { onSettled: () => window.close() })
  return (
    <div role="status" className="sticky top-0 z-40 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-amber-300 bg-amber-100 px-4 py-2 text-sm text-amber-950">
      <FlaskConical className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        <strong>Testing as {me.full_name}</strong> ({me.email}). {me.acted_by.full_name} opened this tab: what you do
        here is done as {me.full_name.split(" ")[0]} and the audit trail says it was a test by {me.acted_by.full_name}.
      </span>
      <button type="button" onClick={end} disabled={logout.isPending}
        className="rounded-md border border-amber-400 bg-white/70 px-2.5 py-1 font-medium hover:bg-white">
        End and close this tab
      </button>
    </div>
  )
}
