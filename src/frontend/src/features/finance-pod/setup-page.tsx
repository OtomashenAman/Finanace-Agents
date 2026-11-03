import { Link } from "react-router"
import { ArrowRight, ShieldCheck } from "lucide-react"

import { Card } from "@/features/service-pod/components/bits"

import { useFinanceMe } from "./hooks"
import { ErpSnapshots } from "./components/erp-snapshots"
import { FinancePage } from "./components/finance-page"
import { SanctionsCard } from "./components/sanctions-card"
import { StatementsCard } from "./components/statements-card"

function MyAccess() {
  const { data: me } = useFinanceMe()
  if (!me) return null
  return (
    <Card title="My capacities" hint="What you may do in the Finance POD. Segregation of duties applies to everyone.">
      {me.is_admin ? (
        <p className="flex items-center gap-2 text-sm">
          <ShieldCheck className="size-4 text-emerald-600" aria-hidden />
          Finance Admin: every capacity, every entity. You still can't approve your own work where the requirement needs a
          second person.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {me.capacities.map((c) => (
            <li key={c.capacity} className="rounded-full border border-border px-3 py-1 text-xs">
              <span className="font-medium">{c.label}</span>{" "}
              <span className="text-muted-foreground">
                {c.entities === null ? "all entities" : c.entities.map((e) => e.code).join(", ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** The POD's setup, away from the day's work: the ERPNext source, the sanctions list, the
 *  month's statements, and who may do what. Each person sees the parts that are theirs. */
export function FinanceSetupPage() {
  const { data: me } = useFinanceMe()
  const billing = me?.is_admin || me?.capacities.some((c) => c.capacity === "billing_analyst")
  return (
    <FinancePage title="Finance POD setup" subtitle="The source data, the lists the agents check against, and who may do what.">
      <div className="space-y-4">
        {me?.is_admin && <ErpSnapshots />}
        {billing && <StatementsCard />}
        {me?.is_admin && <SanctionsCard />}
        <MyAccess />
        {me?.is_admin && (
          <Card title="People and capacities" hint="Grant a person a capacity (requester, buyer, controller, credit controller...) per legal entity or for all.">
            <Link to="/admin/finance-capacities" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
              Manage capacities <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Card>
        )}
      </div>
    </FinancePage>
  )
}
