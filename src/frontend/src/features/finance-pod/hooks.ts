import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { fpodApi, type RequestStatus } from "./api"
import { billingApi, type SalesInvoiceStatus, type SubmissionStatus } from "./billing-api"
import { clientsApi } from "./clients-api"
import { invoicesApi, type ExceptionStatus, type InvoiceStatus } from "./invoices-api"
import { paymentsApi } from "./payments-api"
import { procurementApi, type PoStatus } from "./procurement-api"

/** Every Finance POD query starts with this key; every change refreshes them all. */
export const FPOD_TAG = "fpod"

export function useOverview() {
  return useQuery({ queryKey: [FPOD_TAG, "overview"], queryFn: fpodApi.overview })
}

export function useFinanceSettings() {
  return useQuery({ queryKey: [FPOD_TAG, "settings"], queryFn: fpodApi.settings })
}

export function useReference() {
  return useQuery({ queryKey: [FPOD_TAG, "reference"], queryFn: fpodApi.reference, staleTime: 60_000 })
}

export function useRequests(filters: { status?: RequestStatus | null; mine?: boolean }) {
  return useQuery({ queryKey: [FPOD_TAG, "requests", filters], queryFn: () => fpodApi.requests(filters) })
}

export function useApprovals() {
  return useQuery({ queryKey: [FPOD_TAG, "approvals"], queryFn: fpodApi.approvals })
}

export function useRequest(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "request", id], queryFn: () => fpodApi.request(id!), enabled: Boolean(id) })
}

export function useSourcing(requestId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: [FPOD_TAG, "sourcing", requestId],
    queryFn: () => procurementApi.sourcing(requestId!),
    enabled: Boolean(requestId) && enabled,
  })
}

export function useRequestPo(requestId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: [FPOD_TAG, "request-po", requestId],
    queryFn: () => procurementApi.requestPo(requestId!),
    enabled: Boolean(requestId) && enabled,
  })
}

export function useOnboardings() {
  return useQuery({ queryKey: [FPOD_TAG, "onboardings"], queryFn: procurementApi.onboardings })
}

export function useOnboarding(id: string | undefined) {
  return useQuery({
    queryKey: [FPOD_TAG, "onboarding", id],
    queryFn: () => procurementApi.onboarding(id!),
    enabled: Boolean(id),
  })
}

export function useSanctions() {
  return useQuery({ queryKey: [FPOD_TAG, "sanctions"], queryFn: procurementApi.sanctions })
}

export function usePurchaseOrders(status: PoStatus | null) {
  return useQuery({
    queryKey: [FPOD_TAG, "purchase-orders", status],
    queryFn: () => procurementApi.purchaseOrders(status),
  })
}

export function useMeasures() {
  return useQuery({ queryKey: [FPOD_TAG, "measures"], queryFn: procurementApi.measures })
}

export function useInvoices(status: InvoiceStatus | null, poId: string | null = null) {
  return useQuery({
    queryKey: [FPOD_TAG, "invoices", status, poId],
    queryFn: () => invoicesApi.list(status, poId),
  })
}

export function useInvoice(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "invoice", id], queryFn: () => invoicesApi.get(id!), enabled: Boolean(id) })
}

export function useInvoiceExceptions(status: ExceptionStatus | null) {
  return useQuery({
    queryKey: [FPOD_TAG, "invoice-exceptions", status],
    queryFn: () => invoicesApi.exceptions(status),
  })
}

export function useReceipts(poId: string | undefined) {
  return useQuery({
    queryKey: [FPOD_TAG, "receipts", poId],
    queryFn: () => invoicesApi.receipts(poId!),
    enabled: Boolean(poId),
  })
}

export function useInvoiceMeasures() {
  return useQuery({ queryKey: [FPOD_TAG, "invoice-measures"], queryFn: invoicesApi.measures })
}

export function usePaymentRuns() {
  return useQuery({ queryKey: [FPOD_TAG, "payment-runs"], queryFn: paymentsApi.runs })
}

export function usePaymentRun(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "payment-run", id], queryFn: () => paymentsApi.run(id!), enabled: Boolean(id) })
}

export function useVendorQueries(status: string | null) {
  return useQuery({ queryKey: [FPOD_TAG, "vendor-queries", status], queryFn: () => paymentsApi.queries(status) })
}

export function usePaymentMeasures() {
  return useQuery({ queryKey: [FPOD_TAG, "payment-measures"], queryFn: paymentsApi.measures })
}

export function useClientApplications() {
  return useQuery({ queryKey: [FPOD_TAG, "client-applications"], queryFn: clientsApi.applications })
}

export function useClientApplication(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "client-application", id], queryFn: () => clientsApi.application(id!), enabled: Boolean(id) })
}

export function useClients() {
  return useQuery({ queryKey: [FPOD_TAG, "clients"], queryFn: clientsApi.clients })
}

export function useClient(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "client", id], queryFn: () => clientsApi.client(id!), enabled: Boolean(id) })
}

export function useCreditReviews(openOnly: boolean) {
  return useQuery({ queryKey: [FPOD_TAG, "credit-reviews", openOnly], queryFn: () => clientsApi.reviews(openOnly) })
}

export function useClientMeasures() {
  return useQuery({ queryKey: [FPOD_TAG, "client-measures"], queryFn: clientsApi.measures })
}

export function useSubmissions(status: SubmissionStatus | null) {
  return useQuery({ queryKey: [FPOD_TAG, "lab-submissions", status], queryFn: () => billingApi.submissions(status) })
}

export function useSalesInvoices(status: SalesInvoiceStatus | null) {
  return useQuery({ queryKey: [FPOD_TAG, "sales-invoices", status], queryFn: () => billingApi.invoices(status) })
}

export function useSalesInvoice(id: string | undefined) {
  return useQuery({ queryKey: [FPOD_TAG, "sales-invoice", id], queryFn: () => billingApi.invoice(id!), enabled: Boolean(id) })
}

export function useFeeSchedule() {
  return useQuery({ queryKey: [FPOD_TAG, "fee-schedule"], queryFn: billingApi.feeSchedule })
}

export function useStatements() {
  return useQuery({ queryKey: [FPOD_TAG, "statements"], queryFn: billingApi.statements })
}

export function useBillingMeasures() {
  return useQuery({ queryKey: [FPOD_TAG, "billing-measures"], queryFn: billingApi.measures })
}

/** A change to Finance POD data: on success, refresh every Finance POD query. */
export function useFpodMutation<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (args: A) => fn(...args),
    onSuccess: () => client.invalidateQueries({ queryKey: [FPOD_TAG] }),
  })
}
