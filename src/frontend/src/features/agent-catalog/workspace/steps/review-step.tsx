import { useState, type ReactNode } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { ReviewDecision, RunDetail } from "../api"
import { Panel } from "../components/panel"
import { SourceSnapshot } from "../components/source-snapshot"
import { StatusBadge } from "../components/status-badge"
import { formatDateTime } from "../format"
import { useReviewRun } from "../hooks"

const DECISIONS: { decision: ReviewDecision; label: string; className: string }[] = [
  { decision: "approved", label: "Approve", className: "bg-emerald-700 text-white hover:bg-emerald-800" },
  { decision: "changes_requested", label: "Request changes", className: "bg-amber-600 text-white hover:bg-amber-700" },
  { decision: "rejected", label: "Reject", className: "bg-red-700 text-white hover:bg-red-800" },
]

const DECISION_LABEL: Record<ReviewDecision, string> = {
  approved: "Approved",
  changes_requested: "Changes requested",
  rejected: "Rejected",
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="mt-1 rounded-md border bg-background px-3 py-2 text-sm">{children}</dd>
    </div>
  )
}

export function ReviewStep({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const review = useReviewRun(agentKey, run.id)
  const [comment, setComment] = useState("")
  const [commentError, setCommentError] = useState<string | null>(null)
  const exceptions = run.flags.filter((f) => f.severity === "high" || f.severity === "warning")

  const decide = (decision: ReviewDecision) => {
    if (comment.trim().length < 3) {
      setCommentError("Add a comment explaining your decision")
      return
    }
    setCommentError(null)
    review.mutate(
      { decision, comment: comment.trim() },
      {
        onSuccess: () => {
          setComment("")
          toast.success(`${run.reference}: ${DECISION_LABEL[decision].toLowerCase()}`)
        },
        onError: (error) => toast.error(error instanceof ApiError ? error.message : "Couldn't record the decision"),
      },
    )
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
      <Panel title="Review package">
        <div className="space-y-6">
          <dl className="grid gap-4 sm:grid-cols-2">
            <Fact label="Run identifier">{run.reference}</Fact>
            <Fact label="Preparer">{run.preparer.full_name}</Fact>
            <Fact label="Assigned reviewer">{run.reviewer_label}</Fact>
            <Fact label="Submitted">{formatDateTime(run.submitted_at)}</Fact>
          </dl>

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Proposed decision</h3>
            <p className="mt-1">{run.proposed_decision}</p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">{run.headline}</h3>
            {exceptions.length ? (
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm">
                {exceptions.map((f) => (
                  <li key={f.code} className={cn(f.severity === "high" && "font-medium text-red-800")}>
                    {f.message}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">No exceptions were raised.</p>
            )}
          </div>

          {run.narrative?.output && (
            <div>
              <h3 className="text-sm font-semibold text-brand-navy">AI summary</h3>
              <p className="mt-1 text-sm">{run.narrative.output.summary}</p>
            </div>
          )}

          {run.source && <SourceSnapshot source={run.source} />}

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Evidence</h3>
            {run.documents.length ? (
              <ul className="mt-1.5 space-y-1 text-sm">
                {run.documents.map((d) => (
                  <li key={d.id} className="flex flex-wrap gap-x-2">
                    <span>{d.filename}</span>
                    <span className="font-mono text-xs text-muted-foreground" title={d.sha256}>
                      sha256 {d.sha256.slice(0, 12)}…
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">No supporting documents attached.</p>
            )}
          </div>
        </div>
      </Panel>

      <Panel title="Decision & audit">
        <div className="space-y-6">
          <div>
            <p className="text-sm text-muted-foreground">Current status</p>
            <StatusBadge status={run.status} label={run.status_label} className="mt-1.5" />
          </div>

          {run.permissions.can_review ? (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="review-comment">Review comments</Label>
                <Textarea
                  id="review-comment"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  maxLength={2000}
                  placeholder="What did you verify? Why this decision?"
                  aria-invalid={commentError ? true : undefined}
                  aria-describedby={commentError ? "review-comment-error" : undefined}
                  disabled={review.isPending}
                />
                {commentError && (
                  <p id="review-comment-error" className="text-sm text-destructive">
                    {commentError}
                  </p>
                )}
              </div>
              <div className="grid gap-2">
                {DECISIONS.map(({ decision, label, className }) => (
                  <Button
                    key={decision}
                    size="lg"
                    className={cn("w-full font-semibold", className)}
                    onClick={() => decide(decision)}
                    disabled={review.isPending}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            run.status === "pending_approval" && (
              <p className="text-sm text-muted-foreground">Waiting for {run.reviewer_label} to review this run.</p>
            )
          )}

          {run.reviews.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-brand-navy">Decisions</h3>
              <ol className="mt-2 space-y-3">
                {run.reviews.map((r) => (
                  <li key={r.id} className="rounded-md border bg-background p-3 text-sm">
                    <p className="font-semibold">
                      {DECISION_LABEL[r.decision]} · {r.reviewer.full_name}
                    </p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at)}</p>
                    <p className="mt-1.5">{r.comment}</p>
                    <p className="mt-1.5 font-mono text-xs text-muted-foreground" title={r.result_hash}>
                      result hash {r.result_hash.slice(0, 16)}…
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          )}

          <p className="text-xs text-muted-foreground">Actor, time, comments and result hash are recorded.</p>
        </div>
      </Panel>
    </div>
  )
}
