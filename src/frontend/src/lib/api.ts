const API_BASE = `${import.meta.env.VITE_API_BASE_URL ?? "/api"}/v1`

/** Error thrown for every failed API call. `code` mirrors the backend's detail.code. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /** Per-field messages from a 422 validation error, keyed by field name */
  readonly fieldErrors: Record<string, string>

  constructor(status: number, code: string, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  json?: unknown
  /** multipart upload; the browser sets the Content-Type boundary itself */
  form?: FormData
  headers?: Record<string, string>
  /** Auth endpoints themselves must not trigger the refresh-and-retry dance */
  skipAuthRefresh?: boolean
}

/** User-facing message for a failed call: the server's own message when it sent one. */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = "http_error"
  let message = `Request failed (${res.status}).`
  const fieldErrors: Record<string, string> = {}
  try {
    const { detail } = (await res.json()) as { detail?: unknown }
    if (Array.isArray(detail)) {
      code = "validation_error"
      message = "Please check the highlighted fields."
      for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
        const field = item.loc?.at(-1)
        if (typeof field === "string" && item.msg) fieldErrors[field] = item.msg
      }
    } else if (typeof detail === "string") {
      message = detail
    } else if (detail && typeof detail === "object") {
      const d = detail as { code?: string; message?: string }
      code = d.code ?? code
      message = d.message ?? message
    }
  } catch {
    // non-JSON error body: keep the generic message
  }
  return new ApiError(res.status, code, message, fieldErrors)
}

// One in-flight refresh per tab, shared by every request that got a 401
let refreshing: Promise<boolean> | null = null

function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

export async function apiRequest<T>(
  path: string,
  { json, form, headers, skipAuthRefresh = false, ...init }: RequestOptions = {},
): Promise<T> {
  const send = async () => {
    try {
      return await fetch(`${API_BASE}${path}`, {
        ...init,
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          ...(json !== undefined && { "Content-Type": "application/json" }),
          ...headers,
        },
        body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
      })
    } catch {
      throw new ApiError(0, "network_error", "Can't reach the server. Check your connection and try again.")
    }
  }

  let res = await send()
  if (res.status === 401 && !skipAuthRefresh) {
    await refreshSession()
    // Retry even if this tab's refresh lost a race: another tab may already have new cookies
    res = await send()
  }

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
