/**
 * One folder per workflow, mirroring src/app/service_pod/flows on the backend.
 * Adding a workflow's screens: create flows/<workflow>/ with its case panel (and pages),
 * export its FlowUi from index.ts and add it here; pages go in App.tsx and the POD tabs.
 * Workflows without an entry still work with the generic case screens.
 */
import type { WorkflowKey } from "../api"
import { arCollections } from "./ar-collections"
import { bankRecon } from "./bank-recon"
import type { FlowUi } from "./types"

export const FLOW_UI: Partial<Record<WorkflowKey, FlowUi>> = {
  ar_collections: arCollections,
  bank_recon: bankRecon,
}
