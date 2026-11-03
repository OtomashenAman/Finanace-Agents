import { useState } from "react"
import { Bot, CircleCheck, CircleDashed, CircleSlash, CircleX, RotateCcw, User } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { CaseDetail, Step, StepStatus } from "../api"
import { useCaseAction } from "../hooks"
import { KIND_META, STEP_STATUS, capacityLabel } from "../labels"
import { ChoiceForm } from "./choice-form"
import { NeedForm } from "./need-form"
import { ReceiptForm } from "./receipt-form"
import { ResultForm } from "./result-form"
import { ResultView } from "./result-view"

/** Steps whose form is more than the generic one (lists, pickers from the case's catalogue) */
const FORMS: Record<string, typeof NeedForm> = {
  "ap_purchase_request:1.1.1": NeedForm,
  "ap_purchase_request:1.3.2": ChoiceForm,
  "ap_invoice_match:3.6.2": ReceiptForm,
}

/** A line above a person's form: what the step is for, and where its inputs come from */
const STEP_HINTS: Record<string, string> = {
  "ar_client_account:1.1.1":
    "The client normally fills this in through the portal (Actions → Invite the client). Fill it in here only for an application on paper, after adding its tax form and registration papers under Documents.",
  "ar_client_account:1.2.2": "Read the credit agent's score and proposal above, then decide.",
  "ar_billing:3.3.1": "Read the flags above. Override a rate only if this invoice should differ from the fee schedule.",
  "ap_purchase_request:1.2.2": "Read the budget lines above: an approval over a flagged budget needs a comment.",
  "ap_vendor_onboarding:1.5.2.a": "Call the vendor on a number you found yourself (never the one in the letter or an email), and ask them to read the account's last 4 digits.",
  "ap_invoice_match:3.5.2": "Compare the PO, the receipt and the invoice above, then choose how to settle the difference.",
  "ap_month_close:6.2.1": "Read the accruals, the reconciliation and the statement gaps above.",
}

const STATUS_ICON: Record<StepStatus, typeof CircleCheck> = {
  pending: CircleDashed,
  done: CircleCheck,
  not_applicable: CircleSlash,
  failed: CircleX,
}

/** One L4 task as the requirement draws it: a box in its kind's colour with its L5 steps,
 *  who did each and when, and what the viewer can do on it now. */
export function StepCard({ c, step, open, expandAll = false }: { c: CaseDetail; step: Step; open: boolean; expandAll?: boolean }) {
  const meta = KIND_META[step.kind]
  const action = useCaseAction()
  const [mode, setMode] = useState<"none" | "fail" | "redo">("none")
  const [shown, setShown] = useState(false)
  const [reason, setReason] = useState("")
  const run = (name: string, payload: Record<string, unknown>, done: string) =>
    action.mutate(
      { id: c.id, version: c.version, action: name, payload },
      {
        onSuccess: () => {
          toast.success(done)
          setMode("none")
          setReason("")
        },
        onError: (error) => toast.error(errorMessage(error, "That didn't work.")),
      },
    )
  const canAct = step.blocked === null && c.status !== "completed" && c.status !== "cancelled"
  // Send the earlier step back with the reason, then take the person to its form
  const fixEarlier = (key: string, why: string) =>
    action.mutate(
      { id: c.id, version: c.version, action: "redo_step", payload: { step: key, reason: `To fix: ${why}` } },
      {
        onSuccess: () => {
          toast.success(`Step ${key} is open again: fix it there`)
          setTimeout(() => document.getElementById(`step-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 400)
        },
        onError: (error) => toast.error(errorMessage(error, "Couldn't send it back.")),
      },
    )
  const settled = step.status === "done" || step.status === "not_applicable" || step.status === "failed"
  const KindIcon = step.kind === "agent" ? Bot : User
  // A finished step folds to one line; the current one, a failed one, or one you can act
  // on stays open
  const folded = !open && !expandAll && !shown && (step.status === "done" || step.status === "not_applicable")
  const last = step.l5.filter((l) => l.done_at).at(-1)
  const notes = step.l5.map((l) => l.note)
  const oneNote = step.status === "failed" && notes.every((n) => n && n === notes[0]) ? notes[0] : null

  return (
    <article className={cn("rounded-xl border-2 p-3", meta.box, open && "ring-2 ring-primary/30")} aria-label={`Step ${step.key}`}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full", meta.chip)} title={meta.label}>
            <KindIcon className="size-3.5" aria-hidden />
          </span>
          <h3 className="truncate text-sm font-semibold">{step.title}</h3>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">L4 {step.l4}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {step.capacity && <span className="text-muted-foreground">{capacityLabel(step.capacity)}</span>}
          <span className={cn("rounded-full px-2 py-0.5 font-medium", STEP_STATUS[step.status].className)}>
            {STEP_STATUS[step.status].label}
          </span>
        </div>
      </header>

      {folded ? (
        <p className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            {step.status === "not_applicable"
              ? `Not applicable: ${step.l5[0]?.note ?? ""}`
              : last
                ? `${last.done_by} · ${new Date(last.done_at!).toLocaleString()}`
                : "Done"}
          </span>
          <button type="button" className="font-medium text-primary hover:underline" onClick={() => setShown(true)}>
            Show details
          </button>
        </p>
      ) : (
      <>
      {oneNote && (
        <p className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {oneNote}
          {last?.done_at && <span className="block text-xs text-red-700/80">{last.done_by} · {new Date(last.done_at).toLocaleString()}</span>}
        </p>
      )}
      <ul className="mt-2 space-y-1.5">
        {step.l5.map((l5) => {
          const Icon = STATUS_ICON[l5.status]
          return (
            <li key={l5.code} className="flex gap-2 text-sm">
              <Icon
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  l5.status === "done" ? "text-emerald-600" : l5.status === "failed" ? "text-red-600" : "text-muted-foreground",
                )}
                aria-label={STEP_STATUS[l5.status].label}
              />
              <div className="min-w-0">
                <p>
                  <span className="font-mono text-xs text-muted-foreground">{l5.code}</span> {l5.text}
                </p>
                {l5.result && <ResultView value={l5.result} />}
                {l5.note && !oneNote && <p className="text-xs italic text-muted-foreground">{l5.note}</p>}
                {l5.done_at && !oneNote && (
                  <p className="text-[11px] text-muted-foreground">
                    {l5.done_by} · {new Date(l5.done_at).toLocaleString()}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      </>
      )}
      {shown && !expandAll && (
        <button type="button" className="mt-1 text-xs font-medium text-primary hover:underline" onClick={() => setShown(false)}>
          Hide details
        </button>
      )}

      {step.needs && (
        <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
          <p className="font-medium">The agent won't run yet</p>
          <p className="mt-0.5">
            {step.needs.fix_title ? `In "${step.needs.fix_title}" (${step.needs.fix_step}), ` : ""}
            {step.needs.message}
          </p>
          {step.needs.fix_step && (
            <Button size="sm" className="mt-2" disabled={action.isPending}
              onClick={() => fixEarlier(step.needs!.fix_step!, step.needs!.message)}>
              <RotateCcw className="size-3.5" aria-hidden /> Go back to "{step.needs.fix_title}" and fix it
            </Button>
          )}
        </div>
      )}

      {!settled && !step.needs && step.blocked && step.kind !== "system" && (
        <p className="mt-2 text-xs text-muted-foreground">{step.blocked}</p>
      )}

      {canAct && step.kind === "agent" && (
        <div className="mt-3">
          <Button size="sm" disabled={action.isPending} onClick={() => run("run_agent_step", { step: step.key }, `Step ${step.key} ran`)}>
            <Bot className="size-4" aria-hidden /> {step.status === "failed" ? "Run again" : "Run agent"}
          </Button>
        </div>
      )}

      {canAct && (step.kind === "person" || step.kind === "manual") && mode === "none" && (
        <div className="mt-3 space-y-2">
          {STEP_HINTS[`${c.workflow}:${step.key}`] && (
            <p className="rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-900">{STEP_HINTS[`${c.workflow}:${step.key}`]}</p>
          )}
          {(() => {
            const Custom = FORMS[`${c.workflow}:${step.key}`]
            const submit = (results: Record<string, Record<string, unknown>>) =>
              run("complete_step", { step: step.key, results }, `Step ${step.key} done`)
            return Custom ? (
              <Custom c={c} busy={action.isPending} onSubmit={submit} />
            ) : (
              <ResultForm l5={step.l5} busy={action.isPending} submitLabel={`Complete: ${step.title}`} onSubmit={submit} documents={c.artifacts} />
            )
          })()}
          <Button variant="outline" size="sm" onClick={() => setMode("fail")}>
            Record as failed…
          </Button>
        </div>
      )}

      {!folded && settled && c.status !== "completed" && c.status !== "cancelled" && mode === "none" && (
        <div className="mt-2">
          <Button variant="ghost" size="sm" onClick={() => setMode("redo")}>
            <RotateCcw className="size-3.5" aria-hidden /> Send back…
          </Button>
        </div>
      )}

      {mode !== "none" && (
        <div className="mt-3 space-y-2 rounded-md border border-border/70 bg-background/70 p-3">
          {mode === "redo" && (
            <Alert>Sending {step.key} back resets it and every step after it; approvals given so far stop counting.</Alert>
          )}
          <Input
            aria-label={mode === "fail" ? "Why it failed" : "Why it goes back"}
            placeholder={mode === "fail" ? "Why it failed (e.g. the bank didn't confirm)" : "Why (e.g. which lab is this for?)"}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={mode === "fail" ? "destructive" : "default"}
              disabled={!reason.trim() || action.isPending}
              onClick={() =>
                mode === "fail"
                  ? run("complete_step", { step: step.key, failed_reason: reason.trim() }, `Step ${step.key} recorded as failed`)
                  : run("redo_step", { step: step.key, reason: reason.trim() }, `Step ${step.key} sent back`)
              }
            >
              {mode === "fail" ? "Record failure" : "Send back"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("none")}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </article>
  )
}
