import { TriangleAlert } from "lucide-react"

import type { PurgePreview } from "../api"
import { CASE_STATUS, WORKFLOW_SHORT } from "../labels"
import type { WorkflowKey } from "../api"

/** Exactly what a deletion removes, shown before anything happens. */
export function PurgeSummary({ preview }: { preview: PurgePreview }) {
  const counts: [string, number][] = [
    ["messages", preview.messages],
    ["documents", preview.documents],
    ["posting tasks", preview.posting_tasks],
    ["review tasks", preview.review_tasks],
    ["payment commitments", preview.commitments],
    ["approvals", preview.approvals],
  ]
  const parts = counts.filter(([, n]) => n > 0).map(([label, n]) => `${n} ${label}`)
  return (
    <div className="space-y-2 rounded-lg border border-red-200 bg-red-50/60 p-3 text-xs text-red-950">
      <p className="font-semibold">This deletes, and can't be undone:</p>
      <ul className="list-disc space-y-0.5 pl-4">
        <li>
          {preview.snapshots.length} snapshot{preview.snapshots.length === 1 ? "" : "s"}
          {preview.snapshots.length > 1 && " (including those built on it, e.g. bank statements)"}
        </li>
        <li>
          {preview.cases.length} case{preview.cases.length === 1 ? "" : "s"}
          {preview.cases.length > 0 && (
            <>
              :{" "}
              {preview.cases
                .slice(0, 8)
                .map((c) => `${c.reference} (${WORKFLOW_SHORT[c.workflow as WorkflowKey] ?? c.workflow}, ${CASE_STATUS[c.status][0].toLowerCase()})`)
                .join(", ")}
              {preview.cases.length > 8 && `, and ${preview.cases.length - 8} more`}
            </>
          )}
        </li>
        {parts.length > 0 && <li>with their {parts.join(", ")}</li>}
        {preview.verified_elsewhere > 0 && (
          <li>{preview.verified_elsewhere} verified posting(s) of other cases lose their verifying snapshot (they stay verified, with a note)</li>
        )}
      </ul>
      {preview.evidence && (
        <p className="flex items-start gap-1.5 rounded-md bg-red-100 p-2 font-semibold text-red-900">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          These are real books with approved or completed work or verified postings: the evidence is lost. Archive instead unless you are sure.
        </p>
      )}
      <p className="text-red-900/80">The audit trail keeps a record of who deleted what, and why.</p>
    </div>
  )
}
