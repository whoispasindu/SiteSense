// In development, Vite proxies /api to the backend (see vite.config.ts).
// In production, set VITE_API_BASE_URL to the deployed backend URL.
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api'

/** Error body sent by the backend's central error handler (backend/app/core/errors.py). */
interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
}

/** Thrown for every failed request, so screens can show `message` and branch on `status`/`code`. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  } catch {
    // fetch only rejects when the server could not be reached at all
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.')
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new ApiError(
      response.status,
      body?.error?.code ?? 'http_error',
      body?.error?.message ?? (response.statusText || 'Request failed'),
      body?.error?.details,
    )
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
}
