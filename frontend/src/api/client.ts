import { z } from "zod";

/**
 * Typed API client.
 *
 * Every response is validated at runtime with a Zod schema, so a backend change that breaks the
 * contract fails loudly here instead of rendering `undefined` somewhere deep in the UI. Every
 * failure, whether HTTP, network, timeout or contract, surfaces as an `ApiError`.
 */

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const DEFAULT_TIMEOUT_MS = 15_000;

const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().nullable(),
    details: z.array(z.record(z.string(), z.unknown())),
  }),
});

export type ApiErrorCode =
  | "network_error"
  | "timeout"
  | "invalid_response"
  | "aborted"
  | (string & {});

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>[];

  constructor(options: {
    status: number;
    code: ApiErrorCode;
    message: string;
    requestId?: string | null;
    details?: Record<string, unknown>[];
  }) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? [];
  }

  /** 4xx errors will not succeed on retry; network failures and 5xx might. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status >= 500;
  }
}

export interface RequestOptions<TBody> {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: TBody;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Attach the access token and refresh it once on expiry. Off for the auth endpoints themselves. */
  auth?: boolean;
  acceptStatuses?: readonly number[];
}

// --- Session ------------------------------------------------------------------------------
//
// The access token lives only in this module's memory: never in localStorage or a readable
// cookie, so an injected script cannot lift it from storage. The long-lived refresh token is
// an httpOnly cookie the browser sends to /api/v1/auth only.

let accessToken: string | null = null;

interface SessionHooks {
  /** Obtain a fresh access token using the refresh cookie. Resolves false if the session is over. */
  refresh: () => Promise<boolean>;
  /** Called when the session cannot be recovered, so the app can return to the sign-in page. */
  onExpired: () => void;
}

let hooks: SessionHooks | null = null;
let refreshInFlight: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function configureSession(sessionHooks: SessionHooks | null): void {
  hooks = sessionHooks;
}

/** One refresh at a time: concurrent 401s all wait for the same attempt. */
export function refreshSession(): Promise<boolean> {
  if (!hooks) return Promise.resolve(false);
  refreshInFlight ??= hooks.refresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

const SESSION_ERROR_CODES = new Set(["token_expired", "invalid_token", "session_expired", "unauthorized"]);

export interface ApiResponse<T> {
  data: T;
  status: number;
  requestId: string | null;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export async function apiRequest<TSchema extends z.ZodType, TBody = undefined>(
  path: string,
  schema: TSchema,
  options: RequestOptions<TBody> = {},
): Promise<ApiResponse<z.infer<TSchema>>> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    // Guards against building a request to another origin from a value like "//evil.example".
    throw new Error(`API paths must be absolute and same-origin, got "${path}"`);
  }

  const useAuth = options.auth ?? true;
  try {
    return await send(path, schema, options, useAuth);
  } catch (error) {
    const expired = error instanceof ApiError && error.status === 401 && SESSION_ERROR_CODES.has(error.code);
    if (!useAuth || !expired) throw error;
    if (await refreshSession()) return send(path, schema, options, useAuth);
    hooks?.onExpired();
    throw error;
  }
}

async function send<TSchema extends z.ZodType, TBody>(
  path: string,
  schema: TSchema,
  options: RequestOptions<TBody>,
  useAuth: boolean,
): Promise<ApiResponse<z.infer<TSchema>>> {
  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, acceptStatuses = [] } = options;
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;

  const headers: Record<string, string> = { Accept: "application/json" };
  // FormData (file uploads) sets its own multipart boundary; everything else is JSON.
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (useAuth && accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      credentials: "same-origin",
      redirect: "error",
      signal,
    });
  } catch (cause) {
    if (timeout.aborted) {
      throw new ApiError({ status: 0, code: "timeout", message: "The server took too long to respond." });
    }
    if (options.signal?.aborted) {
      throw new ApiError({ status: 0, code: "aborted", message: "The request was cancelled." });
    }
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Could not reach the server. Check your connection.",
      details: [{ cause: cause instanceof Error ? cause.name : "unknown" }],
    });
  }

  const requestId = response.headers.get("X-Request-ID");
  const payload = await readJson(response);

  if (!response.ok && !acceptStatuses.includes(response.status)) {
    const envelope = errorEnvelopeSchema.safeParse(payload);
    if (envelope.success) {
      const { code, message, request_id, details } = envelope.data.error;
      throw new ApiError({ status: response.status, code, message, requestId: request_id ?? requestId, details });
    }
    throw new ApiError({
      status: response.status,
      code: "http_error",
      message: `The server returned an unexpected error (${String(response.status)}).`,
      requestId,
    });
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError({
      status: response.status,
      code: "invalid_response",
      message: "The server sent a response this app does not understand.",
      requestId,
      details: parsed.error.issues.map((issue) => ({ path: issue.path.join("."), message: issue.message })),
    });
  }

  return { data: parsed.data, status: response.status, requestId };
}

/**
 * Binary download (site photos) with the same auth and refresh rules as ``apiRequest``.
 * Photos are never public URLs: the page fetches them and shows a blob: URL.
 */
export async function apiBlob(path: string, options: { signal?: AbortSignal } = {}): Promise<Blob> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error(`API paths must be absolute and same-origin, got "${path}"`);
  }
  const attempt = async (): Promise<Response> => {
    const headers: Record<string, string> = {};
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    try {
      return await fetch(`${API_BASE_URL}${path}`, {
        headers,
        credentials: "same-origin",
        redirect: "error",
        signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(DEFAULT_TIMEOUT_MS)]) : AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
      });
    } catch {
      throw new ApiError({ status: 0, code: "network_error", message: "Could not load the photo." });
    }
  };
  let response = await attempt();
  if (response.status === 401 && (await refreshSession())) response = await attempt();
  if (!response.ok) {
    throw new ApiError({ status: response.status, code: "http_error", message: "Could not load the photo." });
  }
  return response.blob();
}
