/**
 * One folder per workflow, mirroring src/app/service_pod/flows on the backend.
 * Adding a workflow's screens: create flows/<workflow>/ with its case panel, home page and card
 * stats, export its FlowUi from index.ts and add it here. Routes (/pod/<slug>, /pod/<slug>/cases),
 * the Workflows card and the case page pick it up; the POD tabs never change.
 * Workflows without an entry still work: a card, a cases list and the generic case screens.
 */
import type { WorkflowKey } from "../api"
import { arCollections } from "./ar-collections"
import { bankRecon } from "./bank-recon"
import type { FlowUi } from "./types"

export const FLOW_UI: Partial<Record<WorkflowKey, FlowUi>> = {
  ar_collections: arCollections,
  bank_recon: bankRecon,
}
