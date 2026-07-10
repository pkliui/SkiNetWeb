/**
 * Determines whether an unknown error represents a request timeout.
 *
 * This helper safely inspects errors originating from asynchronous operations
 * such as fetch requests using AbortSignal timeouts. Since caught values in
 * JavaScript can technically be any type, the function performs defensive
 * runtime checks before accessing error properties.
 *
 * The function specifically checks for the standard `name` property used by
 * timeout-related errors:
 *
 *   {
 *     name: "TimeoutError"
 *   }
 *
 * This allows higher-level error handling code to distinguish between:
 *
 * - A request that exceeded its allowed execution time (HTTP 504).
 * - Other failures such as network errors or unavailable services (HTTP 503).
 *
 * @param error
 * Unknown value caught from an exception handler.
 *
 * @returns
 * `true` if the error is identified as a timeout error, otherwise `false`.
 */
export function isTimeoutError(error: unknown): boolean {
    return (
      error instanceof Error &&
      error.name === "TimeoutError"
    );
  }
