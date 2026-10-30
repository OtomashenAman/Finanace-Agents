import { Link } from "react-router"

import type { CaseDetail } from "../api"
import { CASE_STATUS, WORKFLOW_SHORT } from "../labels"
import { Card, Pill } from "./bits"

/** Other workflows' cases about the same customer: the bank receipt that pays an AR
 *  promise, or the promises a receipt relates to. */
export function RelatedCases({ c }: { c: CaseDetail }) {
  if (c.related_cases.length === 0) return null
  return (
    <Card title="Related cases" hint="Same customer, other workflows.">
      <ul className="divide-y text-sm">
        {c.related_cases.map((r) => {
          const [label, tone] = CASE_STATUS[r.status]
          return (
            <li key={r.id} className="py-2">
              <p className="flex flex-wrap items-center gap-2">
                <Link to={`/pod/cases/${r.id}`} className="font-semibold text-primary hover:underline">
                  {r.reference}
                </Link>
                <span className="text-xs text-muted-foreground">{WORKFLOW_SHORT[r.workflow]}</span>
                <Pill label={label} tone={tone} />
              </p>
              {r.summary && <p className="mt-0.5 text-xs">{r.summary}</p>}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
