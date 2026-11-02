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
import { ResultForm } from "./result-form"

const STATUS_ICON: Record<StepStatus, typeof CircleCheck> = {
  pending: CircleDashed,
  done: CircleCheck,
  not_applicable: CircleSlash,
  failed: CircleX,
}

function formatResult(result: Record<string, unknown> | null): string | null {
  if (!result) return null
  const parts = Object.entries(result)
    .filter(([, v]) => v !== null && v !== "")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
  return parts.length ? parts.join(" · ") : null
}

/** One L4 task as the requirement draws it: a box in its kind's colour with its L5 steps,
 *  who did each and when, and what the viewer can do on it now. */
export function StepCard({ c, step, open }: { c: CaseDetail; step: Step; open: boolean }) {
  const meta = KIND_META[step.kind]
  const action = useCaseAction()
  const [mode, setMode] = useState<"none" | "fail" | "redo">("none")
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
  const settled = step.status === "done" || step.status === "not_applicable" || step.status === "failed"
  const KindIcon = step.kind === "agent" ? Bot : User

  return (
    <article className={cn("rounded-xl border-2 p-3", meta.box, open && "ring-2 ring-primary/30")} aria-label={`Step ${step.key}`}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", meta.chip)}>
            <KindIcon className="size-3" aria-hidden />
            {meta.label} · L4 {step.l4}
          </span>
          <h3 className="text-sm font-semibold">{step.title}</h3>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {step.capacity && <span className="text-muted-foreground">{capacityLabel(step.capacity)}</span>}
          <span className={cn("rounded-full px-2 py-0.5 font-medium", STEP_STATUS[step.status].className)}>
            {STEP_STATUS[step.status].label}
          </span>
        </div>
      </header>

      <ul className="mt-2 space-y-1.5">
        {step.l5.map((l5) => {
          const Icon = STATUS_ICON[l5.status]
          const shown = formatResult(l5.result)
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
                {shown && <p className="text-xs text-foreground/80">{shown}</p>}
                {l5.note && <p className="text-xs italic text-muted-foreground">{l5.note}</p>}
                {l5.done_at && (
                  <p className="text-[11px] text-muted-foreground">
                    {l5.done_by} · {new Date(l5.done_at).toLocaleString()}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      {!settled && step.blocked && step.kind !== "system" && (
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
          <ResultForm
            l5={step.l5}
            busy={action.isPending}
            submitLabel={`Complete ${step.key}`}
            onSubmit={(results) => run("complete_step", { step: step.key, results }, `Step ${step.key} done`)}
          />
          <Button variant="outline" size="sm" onClick={() => setMode("fail")}>
            Record as failed…
          </Button>
        </div>
      )}

      {settled && c.status !== "completed" && c.status !== "cancelled" && mode === "none" && (
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
