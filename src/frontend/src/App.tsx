import { QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider } from "react-router"
import { Toaster } from "sonner"

import { AppShell } from "@/components/layout/app-shell"
import { AdminDataSourcesPage } from "@/features/admin/data-sources-page"
import { EntitiesPage } from "@/features/admin/entities-page"
import { GovernancePage } from "@/features/governance/governance-page"
import { UsersPage } from "@/features/admin/users-page"
import { CatalogPage } from "@/features/agent-catalog/catalog-page"
import { RunPage } from "@/features/agent-catalog/workspace/run-page"
import { WorkspacePage } from "@/features/agent-catalog/workspace/workspace-page"
import { LoginPage } from "@/features/auth/login-page"
import { ApprovalsPage } from "@/features/approvals/approvals-page"
import { AccountPage } from "@/features/auth/account-page"
import { HelpPage } from "@/features/help/help-page"
import { AuditPage } from "@/features/audit/audit-page"
import { WorklistPage } from "@/features/worklist/worklist-page"
import { GuestOnly, RequireAdmin, RequireAuth } from "@/features/auth/route-guards"
import { DataSourcesPage } from "@/features/data-sources/data-sources-page"
import { ApprovalsPage as FinanceApprovalsPage } from "@/features/finance-pod/approvals-page"
import { BillingPage } from "@/features/finance-pod/billing-page"
import { ClientApplicationPage } from "@/features/finance-pod/client-application-page"
import { ClientInvoicePage } from "@/features/finance-pod/client-invoice-page"
import { ClientPage } from "@/features/finance-pod/client-page"
import { ClientPortalPage } from "@/features/finance-pod/client-portal-page"
import { ClientsPage } from "@/features/finance-pod/clients-page"
import { FpodShell } from "@/features/finance-pod/components/fpod-shell"
import { CreditReviewsPage } from "@/features/finance-pod/credit-reviews-page"
import { FeeSchedulePage } from "@/features/finance-pod/fee-schedule-page"
import { LabSubmissionsPage } from "@/features/finance-pod/lab-submissions-page"
import { SalesInvoicePage } from "@/features/finance-pod/sales-invoice-page"
import { FinancePodHomePage } from "@/features/finance-pod/home-page"
import { ExceptionsPage } from "@/features/finance-pod/exceptions-page"
import { InvoicePage } from "@/features/finance-pod/invoice-page"
import { InvoicesPage } from "@/features/finance-pod/invoices-page"
import { MeasuresPage } from "@/features/finance-pod/measures-page"
import { NewInvoicePage } from "@/features/finance-pod/new-invoice-page"
import { ReceiptConfirmPage } from "@/features/finance-pod/receipt-page"
import { OrdersPage } from "@/features/finance-pod/orders-page"
import { PaymentRunPage } from "@/features/finance-pod/payment-run-page"
import { PaymentsPage } from "@/features/finance-pod/payments-page"
import { VendorHelpPage } from "@/features/finance-pod/vendor-help-page"
import { VendorQueriesPage } from "@/features/finance-pod/vendor-queries-page"
import { VendorPortalPage } from "@/features/finance-pod/portal-page"
import { VendorPage } from "@/features/finance-pod/vendor-page"
import { VendorsPage } from "@/features/finance-pod/vendors-page"
import { NewRequestPage } from "@/features/finance-pod/new-request-page"
import { RequestPage } from "@/features/finance-pod/request-page"
import { RequestsPage } from "@/features/finance-pod/requests-page"
import { SetupPage } from "@/features/finance-pod/setup-page"
import { AiMonitoringPage } from "@/features/monitoring/ai-monitoring-page"
import { OverviewPage } from "@/features/overview/overview-page"
import { CasePage } from "@/features/service-pod/case-page"
import { CasesPage, LegacyWorkflowCases } from "@/features/service-pod/cases-page"
import { LegacyQueue, MyQueuePage } from "@/features/service-pod/queue-pages"
import { SourcesPage } from "@/features/service-pod/sources-page"
import { DashboardPage } from "@/features/service-pod/dashboard-page"
import { WorkflowHomePage } from "@/features/service-pod/workflows-page"
import { queryClient } from "@/lib/query-client"

const router = createBrowserRouter([
  { element: <GuestOnly />, children: [{ path: "/login", element: <LoginPage /> }] },
  // Vendors' secure onboarding form: no login, the single-use link is the key
  { path: "/vendor-portal/:token", element: <VendorPortalPage /> },
  { path: "/vendor-help", element: <VendorHelpPage /> },
  // Clients apply for an account: the single-use link is the key
  { path: "/client-portal/:token", element: <ClientPortalPage /> },
  // Clients view an invoice from its email: the link is the key
  { path: "/client-invoice/:token", element: <ClientInvoicePage /> },
  // Receivers confirm deliveries from their phone: the single-use link is the key
  { path: "/receipt/:token", element: <ReceiptConfirmPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <Navigate to="/overview" replace /> },
          { path: "/overview", element: <OverviewPage /> },
          { path: "/catalog", element: <CatalogPage /> },
          { path: "/catalog/:agentKey", element: <WorkspacePage /> },
          { path: "/catalog/:agentKey/runs/:runId", element: <RunPage /> },
          { path: "/worklist", element: <WorklistPage /> },
          { path: "/account", element: <AccountPage /> },
          { path: "/help", element: <HelpPage /> },
          { path: "/approvals", element: <ApprovalsPage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/data-sources", element: <DataSourcesPage /> },
          { path: "/pod", element: <DashboardPage /> },
          { path: "/pod/cases", element: <CasesPage /> },
          { path: "/pod/cases/:caseId", element: <CasePage /> },
          { path: "/pod/queue", element: <MyQueuePage /> },
          { path: "/pod/inbox", element: <LegacyQueue type="log" /> },
          { path: "/pod/review", element: <LegacyQueue type="review" /> },
          { path: "/pod/tasks", element: <LegacyQueue type="posting" /> },
          { path: "/pod/sources", element: <SourcesPage /> },
          // A workflow's own screen (where its cases start): /pod/ar, /pod/bank...
          { path: "/pod/:slug", element: <WorkflowHomePage /> },
          { path: "/pod/:slug/cases", element: <LegacyWorkflowCases /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/admin", element: <Navigate to="/admin/users" replace /> },
              { path: "/admin/users", element: <UsersPage /> },
              { path: "/admin/entities", element: <EntitiesPage /> },
              { path: "/admin/governance", element: <GovernancePage /> },
              { path: "/admin/data-sources", element: <AdminDataSourcesPage /> },
              { path: "/admin/ai-monitoring", element: <AiMonitoringPage /> },
            ],
          },
        ],
      },
      {
        // Finance POD: procure-to-pay agents (Finance Admins only), an application of its own
        element: <RequireAdmin />,
        children: [
          {
            element: <FpodShell />,
            children: [
              { path: "/finance-pod", element: <FinancePodHomePage /> },
              { path: "/finance-pod/requests", element: <RequestsPage /> },
              { path: "/finance-pod/requests/new", element: <NewRequestPage /> },
              { path: "/finance-pod/requests/:requestId", element: <RequestPage /> },
              { path: "/finance-pod/approvals", element: <FinanceApprovalsPage /> },
              { path: "/finance-pod/vendors", element: <VendorsPage /> },
              { path: "/finance-pod/vendors/:onboardingId", element: <VendorPage /> },
              { path: "/finance-pod/orders", element: <OrdersPage /> },
              { path: "/finance-pod/measures", element: <MeasuresPage /> },
              { path: "/finance-pod/invoices", element: <InvoicesPage /> },
              { path: "/finance-pod/invoices/new", element: <NewInvoicePage /> },
              { path: "/finance-pod/invoices/:invoiceId", element: <InvoicePage /> },
              { path: "/finance-pod/exceptions", element: <ExceptionsPage /> },
              { path: "/finance-pod/payments", element: <PaymentsPage /> },
              { path: "/finance-pod/payments/:runId", element: <PaymentRunPage /> },
              { path: "/finance-pod/vendor-queries", element: <VendorQueriesPage /> },
              { path: "/finance-pod/clients", element: <ClientsPage /> },
              { path: "/finance-pod/clients/applications/:applicationId", element: <ClientApplicationPage /> },
              { path: "/finance-pod/clients/:clientId", element: <ClientPage /> },
              { path: "/finance-pod/credit-reviews", element: <CreditReviewsPage /> },
              { path: "/finance-pod/lab-submissions", element: <LabSubmissionsPage /> },
              { path: "/finance-pod/billing", element: <BillingPage /> },
              { path: "/finance-pod/billing/:invoiceId", element: <SalesInvoicePage /> },
              { path: "/finance-pod/fee-schedule", element: <FeeSchedulePage /> },
              { path: "/finance-pod/setup", element: <SetupPage /> },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors closeButton />
    </QueryClientProvider>
  )
}
