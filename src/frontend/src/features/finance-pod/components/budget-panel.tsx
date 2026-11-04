import { useState } from "react"
import { CircleAlert, CircleCheck, CircleHelp, Info, RefreshCw, UserRound, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { AiBadge, AiCard, Card, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime, type Tone } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { fpodApi, type Decision, type Finding, type PurchaseRequest, type RouteStep } from "../api"
import { useFpodMutation } from "../hooks"
import { money } from "../labels"

const STEP_STATUS: Record<RouteStep["status"], [string, Tone]> = {
  waiting: ["Waiting", "info"],
  approved: ["Approved", "good"],
  rejected: ["Rejected", "bad"],
  queried: ["Queried", "warn"],
  pending: ["Next", "neutral"],
}

const SEVERITY: Record<Finding["severity"], { icon: typeof XCircle; className: string }> = {
  blocking: { icon: XCircle, className: "text-red-700 dark:text-red-400" },
  acknowledge: { icon: CircleAlert, className: "text-amber-800 dark:text-amber-300" },
  info: { icon: Info, className: "text-muted-foreground" },
}

/** what the budget agent found, and the approval route. */
export function BudgetCheckCard({ r }: { r: PurchaseRequest }) {
  const recheck = useFpodMutation(fpodApi.recheckBudget)
  const check = r.budget_check
  if (!check) return null
  const anyDecided = r.decisions.some((d) => d.round === r.round)
  return (
    <AiCard
      title="Budget agent"
      hint={`budget or grant balance, grant rules and the approval route. Fiscal year ${check.fiscal_year}; checked ${formatDateTime(check.ran_at)}.`}
      badge={<AiBadge label="AI agent" />}
      actions={
        r.status === "submitted" &&
        !anyDecided && (
          <Button
            size="sm"
            variant="outline"
            disabled={recheck.isPending}
            onClick={() => attempt(() => recheck.mutateAsync([r.id]), "Budget re-checked.")}
          >
            <RefreshCw aria-hidden /> Re-check
          </Button>
        )
      }
    >
      <div className="space-y-4 text-sm">
        <section aria-label="Budget impact">
          <h3 className="mb-1 font-semibold">Budget impact</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-1 pr-2 font-medium">Budget line</th>
                  <th className="py-1 pr-2 text-right font-medium">Available</th>
                  <th className="py-1 pr-2 text-right font-medium">This request</th>
                  <th className="py-1 text-right font-medium">After</th>
                </tr>
              </thead>
              <tbody>
                {check.impacts.map((i) => (
                  <tr key={`${i.holder}-${i.category}`} className="border-b border-border/50 align-top">
                    <td className="py-1.5 pr-2">
                      <span className="font-medium">{i.holder}</span>
                      {i.category ? ` · ${i.category}` : ""}
                      <span className="block text-muted-foreground">
                        {i.budget_id
                          ? `budget ${money(i.budget)} − committed ${money(i.committed)} − spent ${money(i.spent)} − approved requests ${money(i.approved_requests)}`
                          : "no budget line"}
                        {` · lines ${i.lines.join(", ")}`}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{money(i.available)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{money(i.this_request)}</td>
                    <td
                      className={cn(
                        "py-1.5 text-right font-semibold tabular-nums",
                        i.over_budget ? "text-red-700 dark:text-red-400" : "text-emerald-700",
                      )}
                    >
                      {money(i.remaining_after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section aria-label="Findings">
          <h3 className="mb-1 font-semibold">Grant rules and budget</h3>
          {check.findings.length === 0 ? (
            <p className="flex items-center gap-1.5 text-emerald-700">
              <CircleCheck className="size-4" aria-hidden /> Within budget; nothing against the grant's rules.
            </p>
          ) : (
            <ul className="space-y-1">
              {check.findings.map((f) => {
                const { icon: Icon, className } = SEVERITY[f.severity]
                return (
                  <li key={f.message} className={cn("flex items-start gap-1.5", className)}>
                    <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span>
                      {f.message}
                      {f.severity === "blocking" && " Blocks approval."}
                      {f.severity === "acknowledge" && " An approver must confirm with a note."}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section aria-label="Approval route">
          <h3 className="mb-1 font-semibold">Approval route (authority matrix)</h3>
          <ol className="space-y-1.5">
            {r.route.map((s) => (
              <li key={s.step} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <UserRound className="size-4 text-sky-700" aria-hidden />
                  <span>
                    {s.step}. <strong>{s.capacity}</strong>: {s.approver_name ?? s.approver_email}
                    {!s.approver_name && <span className="text-xs text-muted-foreground"> (no account)</span>}
                    {Number(s.min_amount) > 0 && (
                      <span className="text-xs text-muted-foreground"> · from {money(s.min_amount)}</span>
                    )}
                  </span>
                </span>
                <Pill label={STEP_STATUS[s.status][0]} tone={STEP_STATUS[s.status][1]} />
              </li>
            ))}
          </ol>
        </section>
      </div>
    </AiCard>
  )
}

/** the budget owner (or the current step's approver) decides. */
export function DecisionCard({ r }: { r: PurchaseRequest }) {
  const decide = useFpodMutation(fpodApi.decide)
  const [note, setNote] = useState("")
  const [ack, setAck] = useState(false)
  if (r.status !== "submitted" || !r.current_step) return null
  const findings = r.budget_check?.findings ?? []
  const blocking = findings.filter((f) => f.severity === "blocking")
  const toAck = findings.filter((f) => f.severity === "acknowledge")
  const step = r.current_step
  const run = (decision: Decision, done: string) =>
    attempt(() => decide.mutateAsync([r.id, r.version, decision, note, ack]), done).then((ok) => {
      if (ok) {
        setNote("")
        setAck(false)
      }
    })

  return (
    <Card
      title={`Decision: ${step.capacity}`}
      hint={
        r.can_decide
          ? `Step ${step.step} of ${r.route.length}. You see the budget impact above; approve, reject or ask the requester.`
          : (r.decide_blocker ?? undefined)
      }
    >
      {r.can_decide ? (
        <div className="space-y-3 text-sm">
          {!step.approver_name && (
            <p className="text-xs text-muted-foreground">
              {step.approver_email} has no Finance Admin account: you decide for them, and it's recorded that way.
            </p>
          )}
          <Textarea
            rows={2}
            value={note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (required to reject, query or approve over budget)"
            aria-label="Decision note"
          />
          {toAck.length > 0 && blocking.length === 0 && (
            <label className="flex items-start gap-2 text-amber-900 dark:text-amber-300">
              <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>I approve despite: {toAck.map((f) => f.message).join(" ")}</span>
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={decide.isPending || blocking.length > 0 || (toAck.length > 0 && (!ack || !note.trim()))}
              title={blocking.length ? "The budget check blocks approval" : undefined}
              onClick={() =>
                run("approve", step.step === r.route.length ? `${r.reference} approved.` : "Step approved; next approver notified.")
              }
            >
              <CircleCheck aria-hidden /> Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={decide.isPending || !note.trim()}
              onClick={() => run("query", "Sent back to the requester with your question.")}
            >
              <CircleHelp aria-hidden /> Query requester
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={decide.isPending || !note.trim()}
              onClick={() => run("reject", `${r.reference} rejected.`)}
            >
              <XCircle aria-hidden /> Reject
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{r.decide_blocker}</p>
      )}
    </Card>
  )
}

const DECISION_TEXT: Record<Decision, string> = { approve: "Approved", reject: "Rejected", query: "Queried" }

export function DecisionHistory({ r }: { r: PurchaseRequest }) {
  if (r.decisions.length === 0) return null
  return (
    <Card title="Decisions" hint="Every round, oldest first. A resubmission starts a new round.">
      <ul className="space-y-2 text-sm">
        {r.decisions.map((d) => (
          <li key={d.id} className="border-b border-border/50 pb-2">
            <p>
              <strong>{DECISION_TEXT[d.decision]}</strong> by {d.decided_by_name} as {d.capacity}
              {d.acting_for && ` for ${d.acting_for}`}
              <span className="text-xs text-muted-foreground">
                {" "}
                · round {d.round} · {formatDateTime(d.created_at)}
              </span>
            </p>
            {d.note && <p className="mt-0.5 whitespace-pre-wrap text-muted-foreground">“{d.note}”</p>}
            <p className="mt-0.5 flex flex-wrap gap-1">
              {d.budget_acknowledged && <Pill label="Approved over budget / with exceptions" tone="warn" />}
              {d.self_approval && <Pill label="Own request: self-approval allowed" tone="warn" />}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  )
}
