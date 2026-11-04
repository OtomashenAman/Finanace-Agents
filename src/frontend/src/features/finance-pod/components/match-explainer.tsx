import { useEffect, useRef } from "react"
import { ArrowRight, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { formatDateTime } from "@/features/service-pod/labels"
import { cn } from "@/lib/utils"

import { useFpodMutation } from "../hooks"
import { invoicesApi, type Invoice, type TrailLine } from "../invoices-api"
import { money } from "../labels"

/** Ordered -> received -> billed before -> this invoice -> left to bill, for one line. */
function Trail({ t }: { t: TrailLine }) {
  const steps = [
    { label: "Ordered on PO", value: t.ordered, tone: "border-border" },
    { label: "Received", value: t.received, tone: Number(t.received) < Number(t.billed_before) + Number(t.this_invoice) ? "border-amber-400 bg-amber-50" : "border-border" },
    { label: "Billed before", value: t.billed_before, tone: "border-border" },
    { label: "This invoice", value: t.this_invoice, tone: "border-primary bg-primary/5" },
    { label: "Left to bill", value: t.left_to_bill, tone: Number(t.left_to_bill) < 0 ? "border-red-400 bg-red-50" : "border-border" },
  ]
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium">
        Line {t.line} → PO line {t.po_line}: {t.description}
        <span className="text-muted-foreground">
          {" "}
          · {money(t.unit_price)} a unit (PO {money(t.po_unit_price)})
        </span>
      </p>
      <ol className="flex flex-wrap items-center gap-1.5">
        {steps.map((s, i) => (
          <li key={s.label} className="flex items-center gap-1.5">
            <span className={cn("rounded-lg border px-2.5 py-1 text-center", s.tone)}>
              <span className="block text-base font-semibold tabular-nums">{s.value}</span>
              <span className="block text-[10px] text-muted-foreground">{s.label}</span>
            </span>
            {i < steps.length - 1 && <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** The match agent's explanation: sentences that cite computed figures, shown with them. */
export function MatchExplainer({ inv }: { inv: Invoice }) {
  const explain = useFpodMutation(invoicesApi.explain)
  const asked = useRef<string | null>(null)
  const m = inv.match
  const key = `${inv.id}-${m?.ran_at}`
  // Explain each new match once, by itself
  useEffect(() => {
    if (m && !m.explanation && !m.explanation_error && asked.current !== key) {
      asked.current = key
      explain.mutate([inv.id])
    }
  }, [m, key, inv.id, explain])
  if (!m) return null
  const facts = new Map((m.explanation?.facts ?? []).map((f) => [f.id, f]))
  return (
    <div className="space-y-3">
      {(m.trail ?? []).length > 0 && (
        <div className="space-y-2 rounded-lg border border-border/80 p-3">
          <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">Quantity trail</p>
          {m.trail!.map((t) => (
            <Trail key={t.line} t={t} />
          ))}
        </div>
      )}
      <div className="rounded-lg border border-violet-200 bg-violet-50/60 p-3 dark:border-violet-900/50 dark:bg-violet-950/20">
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-violet-800 dark:text-violet-300">
          <Sparkles className="size-3.5" aria-hidden /> Match agent explains
        </p>
        {m.explanation ? (
          <ul className="space-y-2 text-sm">
            {m.explanation.highlights.map((h, i) => (
              <li key={i}>
                {h.text}
                <span className="mt-0.5 flex flex-wrap gap-1">
                  {h.fact_ids.map((id) => {
                    const f = facts.get(id)
                    return f ? (
                      <span key={id} className="rounded bg-white/80 px-1.5 py-0.5 text-[11px] text-muted-foreground ring-1 ring-violet-200 dark:bg-transparent" title={f.label}>
                        {f.label}: <strong className="text-foreground">{f.value}</strong>
                      </span>
                    ) : null
                  })}
                </span>
              </li>
            ))}
            <li className="text-[11px] text-muted-foreground">
              Every figure comes from the match itself; the AI only cites them. {formatDateTime(m.explanation.generated_at)}
            </li>
          </ul>
        ) : explain.isPending ? (
          <p className="text-sm text-muted-foreground">The match agent is writing its explanation…</p>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
            <span>{m.explanation_error ? `No explanation: ${m.explanation_error}. The quantity trail above has the figures.` : "No explanation yet."}</span>
            <Button size="sm" variant="outline" onClick={() => explain.mutate([inv.id])}>
              <Sparkles aria-hidden /> Explain
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
