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
}

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
  options: RequestOptions<TBody> & { acceptStatuses?: readonly number[] } = {},
): Promise<ApiResponse<z.infer<TSchema>>> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    // Guards against building a request to another origin from a value like "//evil.example".
    throw new Error(`API paths must be absolute and same-origin, got "${path}"`);
  }

  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, acceptStatuses = [] } = options;
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
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
