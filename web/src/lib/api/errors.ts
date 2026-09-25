import type { components } from "./schema";

type ValidationIssue = components["schemas"]["ValidationError"];

/** Backend errors are `{"detail": string}`; 422 validation errors are `{"detail": [{loc, msg, type}]}`. */
export type ErrorBody = { detail?: string | ValidationIssue[] };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ErrorBody["detail"];

  constructor(status: number, body: unknown) {
    const detail = (body as ErrorBody | undefined)?.detail;
    super(detailMessage(detail) ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export const OFFLINE_MESSAGE = "You're offline. Check your connection and try again.";

function detailMessage(detail: ErrorBody["detail"]): string | undefined {
  if (typeof detail === "string") return detail;
  return detail?.[0]?.msg;
}

/** `fetch` rejects (rather than returning a response) when the network is down. */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

/** A user-facing sentence for any error thrown by an API call. */
export function errorMessage(error: unknown, fallback = "Something went wrong. Try again."): string {
  if (isNetworkError(error)) return OFFLINE_MESSAGE;
  if (error instanceof ApiError && error.status < 500) return error.message;
  return fallback;
}

/** Turns an openapi-fetch result into its data, or throws an `ApiError`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    throw new ApiError(result.response.status, result.error);
  }
  return result.data as T;
}
