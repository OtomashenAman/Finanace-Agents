import { LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { useUsers } from "@/features/admin/hooks"
import { AdminTabs } from "@/features/admin/components/admin-tabs"

import { ApprovalMatrixCard } from "./components/approval-matrix-card"
import { MakerCheckerCard } from "./components/maker-checker-card"
import { PolicyCard } from "./components/policy-card"
import { useMatrices, usePolicies } from "./hooks"

/** Finance Admin controls (PDF p.3): maker-checker, versioned thresholds, approval matrix. */
export function GovernancePage() {
  const policies = usePolicies()
  const matrices = useMatrices()
  const users = useUsers("")
  const admins = (users.data ?? []).filter((u) => u.role === "finance_admin" && u.is_active)

  return (
    <AppPage
      title="Admin Settings · Governance"
      subtitle="Who may approve what, and the thresholds the agents apply. Every change is versioned or audited."
    >
      <AdminTabs />
      <div className="space-y-8">
        <MakerCheckerCard />

        <section className="space-y-4" aria-labelledby="thresholds-title">
          <div>
            <h2 id="thresholds-title" className="text-lg font-semibold text-brand-navy">
              Thresholds
            </h2>
            <p className="text-sm text-muted-foreground">
              Saving creates a new policy version. Each run records the version and values it was analyzed with.
            </p>
          </div>
          {policies.isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
          {policies.isError && <Alert>Couldn't load thresholds.</Alert>}
          {policies.data?.length === 0 && <p className="text-sm text-muted-foreground">No agent has adjustable thresholds yet.</p>}
          {policies.data?.map((p) => <PolicyCard key={`${p.agent_key}-${p.current.version_label}`} policy={p} />)}
        </section>

        <section className="space-y-4" aria-labelledby="matrix-title">
          <div>
            <h2 id="matrix-title" className="text-lg font-semibold text-brand-navy">
              Approval matrix
            </h2>
            <p className="text-sm text-muted-foreground">
              By amount: how many Finance Admin approvals a submitted run needs, and which admins may give them.
            </p>
          </div>
          {(matrices.isPending || users.isPending) && (
            <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />
          )}
          {matrices.isError && <Alert>Couldn't load the approval matrix.</Alert>}
          {matrices.data &&
            users.data &&
            matrices.data.map((m) => (
              <ApprovalMatrixCard key={`${m.agent_key}-${JSON.stringify(m.tiers)}`} matrix={m} admins={admins} />
            ))}
        </section>
      </div>
    </AppPage>
  )
}
