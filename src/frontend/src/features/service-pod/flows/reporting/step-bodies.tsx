import { Download, FileText, Mail } from "lucide-react"

import { Button } from "@/components/ui/button"
import { apiDownload } from "@/lib/api"

import type { CaseDetail } from "../../api"
import { Card, Empty, Pill } from "../../components/bits"
import { Messages } from "../../components/case-messages"
import { ReviewTasks } from "../../components/case-sections"
import { useCompose, useCreateDraft, useExportPack, useReportMonths, useReportPacks } from "../../hooks"
import { formatDateTime } from "../../labels"
import { attempt } from "../../ui"
import { CheckRow } from "../shared-ui"
import { amount, marginLabel, monthLabel, pct, signed } from "../fpa-trend/meta"
import { Commentary, Corrections, FollowUps, TrendsAndDrivers } from "../fpa-trend/step-bodies"
import { reportState } from "./meta"

// --- 1. month & controls -----------------------------------------------------------------

export function MonthAndControls({ c }: { c: CaseDetail }) {
  const s = reportState(c)
  const issues = s.issues.filter((i) => i.blocking)
  const scope = c.review_tasks.filter((t) => t.kind === "scope")
  return (
    <>
      <Card
        title={`${monthLabel(s.report_month)} against ${monthLabel(s.prior_month)}`}
        hint={`${s.basis} basis · ${s.currency}${s.business_unit ? ` · ${s.business_unit}` : " · whole company"}`}
      >
        <ul className="text-sm">
          {s.controls.map((ctl) => (
            <CheckRow key={ctl.key} state={ctl.status === "pass" ? "done" : "failed"} label={ctl.label}>
              {ctl.detail}
            </CheckRow>
          ))}
          <CheckRow state={s.aging.matches_month_end ? "done" : scope.some((t) => t.status === "open") ? "waiting" : "done"} label="Aging date">
            {s.aging.matches_month_end
              ? "AR aging is as of the month end"
              : `AR aging is as of ${s.aging.as_of}, not ${s.aging.month_end}: ${scope.some((t) => t.status === "open") ? "the Controller must settle it" : "settled"}`}
          </CheckRow>
        </ul>
        {issues.length > 0 && (
          <ul className="mt-3 space-y-1.5 border-t pt-3 text-sm text-red-800">
            {issues.map((i) => (
              <li key={i.detail}>{i.detail}</li>
            ))}
          </ul>
        )}
        {s.close.required_checks.length > 0 && (
          <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">Close checklist in the source: {s.close.required_checks.join(" · ")}</p>
        )}
        {s.caveats.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 border-t pt-3 pl-5 text-xs text-amber-800">
            {s.caveats.map((cv) => (
              <li key={cv}>{cv}</li>
            ))}
          </ul>
        )}
      </Card>
      {scope.length > 0 && <ReviewTasks c={c} />}
    </>
  )
}

// --- 2. statements & variance -------------------------------------------------------------

function Statements({ c }: { c: CaseDetail }) {
  const s = reportState(c)
  const prior = s.metrics.find((m) => m.period === s.prior_month)!
  const cur = s.metrics.find((m) => m.period === s.report_month)!
  const change = s.changes[s.changes.length - 1]!
  const rows: [string, keyof typeof cur, keyof typeof change | null][] = [
    ["Revenue", "revenue", "revenue"],
    ["Cost of services", "cost_of_services", "cost_of_services"],
    ["Gross profit", "gross_profit", null],
    ["Operating expenses", "operating_expense", "operating_expense"],
    ["Operating profit", "operating_profit", "operating_profit"],
  ]
  const sheets = s.balance_sheets
  return (
    <>
      <Card title="Profit and loss" hint="As the source states it; the report month against the month before.">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground uppercase">
              <th className="py-1.5 pr-3 font-semibold" />
              <th className="py-1.5 pr-3 text-right font-semibold">{monthLabel(s.prior_month)}</th>
              <th className="py-1.5 pr-3 text-right font-semibold">{monthLabel(s.report_month)}</th>
              <th className="py-1.5 text-right font-semibold">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map(([label, key, move]) => {
              const m = move ? (change[move] as { change: string; pct: string | null }) : null
              return (
                <tr key={label}>
                  <td className="py-1.5 pr-3">{label}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(prior[key] as string, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(cur[key] as string, s.currency)}</td>
                  <td className="py-1.5 text-right tabular-nums">{m ? `${signed(m.change, s.currency)} (${pct(m.pct)})` : ""}</td>
                </tr>
              )
            })}
            <tr>
              <td className="py-1.5 pr-3">Operating margin</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{marginLabel(prior.margin_pct)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{marginLabel(cur.margin_pct)}</td>
              <td className="py-1.5 text-right tabular-nums">{change.margin_pp_exact === null ? "undefined" : `${pct(change.margin_pp_exact, 2).replace("%", "")} pp`}</td>
            </tr>
          </tbody>
        </table>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Balance sheet" hint="Assets must equal liabilities plus equity within half a cent.">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground uppercase">
                <th className="py-1.5 pr-3 font-semibold" />
                <th className="py-1.5 pr-3 text-right font-semibold">{monthLabel(s.prior_month, true)}</th>
                <th className="py-1.5 text-right font-semibold">{monthLabel(s.report_month, true)}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {(["assets", "liabilities", "equity"] as const).map((k) => (
                <tr key={k}>
                  <td className="py-1.5 pr-3 capitalize">{k}</td>
                  {[s.prior_month, s.report_month].map((m) => (
                    <td key={m} className="py-1.5 pr-3 text-right tabular-nums last:pr-0">
                      {sheets[m] ? amount(sheets[m]![k], s.currency) : <Pill label="missing" tone="bad" />}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="py-1.5 pr-3 text-xs text-muted-foreground">Balanced</td>
                {[s.prior_month, s.report_month].map((m) => (
                  <td key={m} className="py-1.5 pr-3 text-right last:pr-0">
                    {sheets[m] ? <Pill label={sheets[m]!.balanced ? "Yes" : `Off ${sheets[m]!.difference}`} tone={sheets[m]!.balanced ? "good" : "bad"} /> : "-"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </Card>
        <Card title="AR aging" hint={`Open balances as of ${s.aging.as_of}${s.aging.matches_month_end ? "" : ` (not the month end ${s.aging.month_end})`}.`}>
          <table className="w-full text-sm">
            <tbody className="divide-y">
              {s.aging.buckets.map((b) => (
                <tr key={b.label}>
                  <td className="py-1.5 pr-3">{b.label}</td>
                  <td className="py-1.5 pr-3 text-right text-xs text-muted-foreground">{b.count} inv.</td>
                  <td className="py-1.5 text-right tabular-nums">{amount(b.amount, s.currency)}</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="py-1.5 pr-3">Total</td>
                <td />
                <td className="py-1.5 text-right tabular-nums">{amount(s.aging.total, s.currency)}</td>
              </tr>
            </tbody>
          </table>
        </Card>
      </div>
    </>
  )
}

export function StatementsAndVariance({ c }: { c: CaseDetail }) {
  return (
    <>
      <Statements c={c} />
      <TrendsAndDrivers c={c} />
    </>
  )
}

// --- 3. Controller review ---------------------------------------------------------------

export function ControllerReview({ c }: { c: CaseDetail }) {
  const s = reportState(c)
  const others = c.review_tasks.filter((t) => t.kind !== "scope")
  return (
    <>
      <Commentary c={c} s={s} title="Pack commentary" />
      <FollowUps c={c} s={s} />
      {others.length > 0 && <ReviewTasks c={c} />}
      <Corrections c={c} s={s} />
    </>
  )
}

// --- 4. CFO approval, pack and distribution --------------------------------------------

function ApprovalRecord({ c }: { c: CaseDetail }) {
  return (
    <Card title="Approval record" hint="The Controller reviews the evidence; the CFO approves the same content. An edit asks for both again.">
      <ul className="text-sm">
        {["Controller", "CFO"].map((cap) => {
          const a = c.approvals.filter((x) => x.valid && x.capacity === cap).at(-1)
          return (
            <CheckRow key={cap} state={a ? "done" : c.next_signoff === cap ? "waiting" : "na"} label={cap}>
              {a ? `Signed off by ${a.user.name} · ${formatDateTime(a.created_at)}` : c.next_signoff === cap ? "Waiting for this sign-off" : "After the Controller"}
            </CheckRow>
          )
        })}
      </ul>
    </Card>
  )
}

function PackCard({ c }: { c: CaseDetail }) {
  const { data: packs = [] } = useReportPacks(c.id)
  const exportPack = useExportPack()
  const signed = c.status === "approved" || c.status === "completed"
  const current = packs.find((p) => p.current)
  return (
    <Card
      title="Management pack (PDF)"
      hint="Made only from the content both sign-offs cover, stored once and checked byte for byte when downloaded."
      actions={
        signed && !current ? (
          <Button size="sm" disabled={exportPack.isPending} onClick={() => void attempt(() => exportPack.mutateAsync(c.id), (p) => `Pack v${p.number} exported.`)}>
            <FileText /> Export pack
          </Button>
        ) : undefined
      }
    >
      {!signed && <Empty>The pack is exported after the CFO signs off.</Empty>}
      {packs.length > 0 && (
        <ul className="divide-y">
          {[...packs].reverse().map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
              <span className="font-semibold">Version {p.number}</span>
              <Pill label={p.current ? "Current" : "Superseded"} tone={p.current ? "good" : "neutral"} />
              <span className="text-xs text-muted-foreground" title={p.sha256}>
                SHA-256 {p.sha256.slice(0, 12)}… · {(p.size / 1024).toFixed(1)} KB · {formatDateTime(p.created_at)}
              </span>
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => void apiDownload(`/pod/reporting/cases/${c.id}/packs/${p.id}.pdf`, `${c.reference}-pack-v${p.number}.pdf`)}>
                <Download /> PDF
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Distribution({ c }: { c: CaseDetail }) {
  const { data: months } = useReportMonths()
  const { data: packs = [] } = useReportPacks(c.id)
  const compose = useCompose()
  const draft = useCreateDraft()
  const current = packs.find((p) => p.current)
  const recipients = months?.internal_recipients ?? []
  const drafted = c.messages.some((m) => m.purpose === "pack_distribution")
  return (
    <>
      {!drafted && (
        <Card title="Distribution" hint="Only to the configured internal recipients; the email carries the exact saved PDF.">
          {recipients.length === 0 ? (
            <p className="text-sm text-amber-800">No internal recipients are configured (POD_INTERNAL_RECIPIENTS), so the pack can't be sent yet.</p>
          ) : (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="flex-1 text-muted-foreground">To {recipients.join(", ")}</span>
              <Button
                size="sm"
                disabled={!current || compose.isPending || draft.isPending || c.status !== "approved"}
                title={current ? undefined : "Export the pack first"}
                onClick={() =>
                  void attempt(async () => {
                    const d = await compose.mutateAsync({ caseId: c.id, purpose: "pack_distribution" })
                    return draft.mutateAsync({
                      caseId: c.id,
                      draft: {
                        audience: "internal",
                        purpose: "pack_distribution",
                        to_email: d.to_email ?? recipients[0]!,
                        to_name: d.to_name,
                        subject: d.subject,
                        body: d.body,
                        artifact_ids: [current!.artifact_id],
                      },
                    })
                  }, "Email drafted with the pack attached: check it, then send.")
                }
              >
                <Mail /> Draft the pack email
              </Button>
            </div>
          )}
        </Card>
      )}
      {drafted && (
        <Messages
          c={c}
          title="Distribution"
          hint="Only to the configured internal recipients; the email carries the exact saved PDF."
          filter={(m) => m.purpose === "pack_distribution"}
          compose={false}
          importReplies={false}
          empty="Nothing sent yet."
        />
      )}
    </>
  )
}

export function CfoApproval({ c }: { c: CaseDetail }) {
  return (
    <>
      <ApprovalRecord c={c} />
      <PackCard c={c} />
      <Distribution c={c} />
    </>
  )
}
