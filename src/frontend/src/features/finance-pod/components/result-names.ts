import { createContext, useContext } from "react"

import type { CaseDetail } from "../api"

/** Ids a step result may carry (a message, a document, a posting) and what to show instead. */
export const ResultNames = createContext<Record<string, string>>({})

export function useResultNames(): Record<string, string> {
  return useContext(ResultNames)
}

export function namesOf(c: CaseDetail): Record<string, string> {
  const names: Record<string, string> = {}
  for (const m of c.messages) names[m.id] = `Mail: ${m.subject}`
  for (const a of c.artifacts) names[a.id] = a.filename
  for (const t of c.posting_tasks) {
    const what = t.kind.replace(/^create_/, "").replace(/_/g, " ")
    names[t.id] = t.external_txn_id ? `${what} ${t.external_txn_id}` : `${what} (${t.reference})`
  }
  return names
}
