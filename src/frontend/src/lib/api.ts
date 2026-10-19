const API_BASE = `${import.meta.env.VITE_API_BASE_URL ?? "/api"}/v1`

/** Error thrown for every failed API call. `code` mirrors the backend's detail.code. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
  }
}

interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  json?: unknown
  headers?: Record<string, string>
  /** Auth endpoints themselves must not trigger the refresh-and-retry dance */
  skipAuthRefresh?: boolean
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = "http_error"
  let message = `Request failed (${res.status}).`
  try {
    const { detail } = (await res.json()) as { detail?: unknown }
    if (Array.isArray(detail)) {
      code = "validation_error"
      message = "Please check the highlighted fields."
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
  return new ApiError(res.status, code, message)
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
  { json, headers, skipAuthRefresh = false, ...init }: RequestOptions = {},
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
        body: json !== undefined ? JSON.stringify(json) : undefined,
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
