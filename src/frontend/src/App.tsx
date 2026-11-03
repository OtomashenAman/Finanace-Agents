import { QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider } from "react-router"
import { Toaster } from "sonner"

import { AppShell } from "@/components/layout/app-shell"
import { AdminDataSourcesPage } from "@/features/admin/data-sources-page"
import { EntitiesPage } from "@/features/admin/entities-page"
import { FinanceCapacitiesPage } from "@/features/admin/finance-capacities-page"
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
import { FinanceCasePage } from "@/features/finance-pod/case-page"
import { FinanceCasesPage } from "@/features/finance-pod/cases-page"
import { FinanceDashboardPage } from "@/features/finance-pod/dashboard-page"
import { VendorPortalPage } from "@/features/finance-pod/vendor-portal-page"
import { ClientPortalPage } from "@/features/finance-pod/client-portal-page"
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
  // A vendor's secure upload page: no account, the signed link is the access
  { path: "/vendor/:token", element: <VendorPortalPage /> },
  { path: "/client/:token", element: <ClientPortalPage /> },
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
          // Finance POD: the AP / AR agents (its own tab and API, the shared case engine)
          { path: "/finance", element: <FinanceDashboardPage /> },
          { path: "/finance/cases", element: <FinanceCasesPage /> },
          { path: "/finance/cases/:caseId", element: <FinanceCasePage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/admin", element: <Navigate to="/admin/users" replace /> },
              { path: "/admin/users", element: <UsersPage /> },
              { path: "/admin/entities", element: <EntitiesPage /> },
              { path: "/admin/governance", element: <GovernancePage /> },
              { path: "/admin/finance-capacities", element: <FinanceCapacitiesPage /> },
              { path: "/admin/data-sources", element: <AdminDataSourcesPage /> },
              { path: "/admin/ai-monitoring", element: <AiMonitoringPage /> },
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
