import { QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider } from "react-router"
import { Toaster } from "sonner"

import { AppShell } from "@/components/layout/app-shell"
import { AdminDataSourcesPage } from "@/features/admin/data-sources-page"
import { UsersPage } from "@/features/admin/users-page"
import { CatalogPage } from "@/features/agent-catalog/catalog-page"
import { RunPage } from "@/features/agent-catalog/workspace/run-page"
import { WorkspacePage } from "@/features/agent-catalog/workspace/workspace-page"
import { LoginPage } from "@/features/auth/login-page"
import { ApprovalsPage } from "@/features/approvals/approvals-page"
import { AuditPage } from "@/features/audit/audit-page"
import { GuestOnly, RequireAdmin, RequireAuth } from "@/features/auth/route-guards"
import { DataSourcesPage } from "@/features/data-sources/data-sources-page"
import { OverviewPage } from "@/features/overview/overview-page"
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
          { path: "/approvals", element: <ApprovalsPage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/data-sources", element: <DataSourcesPage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/admin", element: <Navigate to="/admin/users" replace /> },
              { path: "/admin/users", element: <UsersPage /> },
              { path: "/admin/data-sources", element: <AdminDataSourcesPage /> },
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
