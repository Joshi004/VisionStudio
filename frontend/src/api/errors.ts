/** An error answer from the backend, carrying its readable `detail` message. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * The backend's `detail` message, only when it is a string. FastAPI's own
 * request validation errors use a list there, which is not meant to be shown.
 */
export function detailMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string" && detail !== "") {
      return detail;
    }
  }
  return fallback;
}

/** A readable message for any error a query or mutation can end with. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "Could not reach the backend. Check that it is running, then try again.";
}
