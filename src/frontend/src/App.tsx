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
import { AiMonitoringPage } from "@/features/monitoring/ai-monitoring-page"
import { OverviewPage } from "@/features/overview/overview-page"
import { PodAssignmentsPage } from "@/features/service-pod/assignments-page"
import { CasePage } from "@/features/service-pod/case-page"
import { CasesPage } from "@/features/service-pod/cases-page"
import { InboxPage, ReviewQueuePage, TasksPage } from "@/features/service-pod/queue-pages"
import { SourcesPage } from "@/features/service-pod/sources-page"
import { queryClient } from "@/lib/query-client"

const router = createBrowserRouter([
  { element: <GuestOnly />, children: [{ path: "/login", element: <LoginPage /> }] },
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
          { path: "/pod", element: <Navigate to="/pod/cases" replace /> },
          { path: "/pod/cases", element: <CasesPage /> },
          { path: "/pod/cases/:caseId", element: <CasePage /> },
          { path: "/pod/inbox", element: <InboxPage /> },
          { path: "/pod/review", element: <ReviewQueuePage /> },
          { path: "/pod/tasks", element: <TasksPage /> },
          { path: "/pod/sources", element: <SourcesPage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/admin", element: <Navigate to="/admin/users" replace /> },
              { path: "/admin/users", element: <UsersPage /> },
              { path: "/admin/entities", element: <EntitiesPage /> },
              { path: "/admin/governance", element: <GovernancePage /> },
              { path: "/admin/data-sources", element: <AdminDataSourcesPage /> },
              { path: "/admin/ai-monitoring", element: <AiMonitoringPage /> },
              { path: "/admin/service-pod", element: <PodAssignmentsPage /> },
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
