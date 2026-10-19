import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider } from "react-router"
import { Toaster } from "sonner"

import { authKeys } from "@/features/auth/hooks"
import { LoginPage } from "@/features/auth/login-page"
import { GuestOnly, RequireAuth } from "@/features/auth/route-guards"
import { DashboardPage } from "@/features/dashboard/dashboard-page"
import { ApiError } from "@/lib/api"

// A 401 that survived the refresh retry means the session is gone: sign the user out
function onApiError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    queryClient.setQueryData(authKeys.me, null)
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onApiError }),
  mutationCache: new MutationCache({ onError: onApiError }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Retry only transient failures, never 4xx
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter([
  { element: <GuestOnly />, children: [{ path: "/login", element: <LoginPage /> }] },
  { element: <RequireAuth />, children: [{ path: "/", element: <DashboardPage /> }] },
  { path: "*", element: <Navigate to="/" replace /> },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  )
}
