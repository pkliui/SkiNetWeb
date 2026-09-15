/**
 * Centralized error handling utilities for service-layer failures.
 *
 * This module provides:
 *
 * - A typed error class for failures originating from upstream services.
 * - A helper function for converting internal service errors into consistent
 *   HTTP responses.
 *
 * Error handling flow:
 *
 *   External service failure
 *            |
 *            v
 *   Service layer throws UpstreamServiceError
 *            |
 *            v
 *   Router catches error
 *            |
 *            v
 *   sendServiceError()
 *            |
 *            v
 *   HTTP response returned to client
 *
 * Design goals:
 *
 * - Preserve structured error payloads from upstream services.
 * - Avoid exposing raw internal exceptions.
 * - Provide consistent timeout and availability responses.
 *
 * This keeps HTTP error formatting separate from business and integration
 * logic.
 */

import type { Response } from "express";

import { isTimeoutError } from "./timeout.js";

/**
 * Represents a failure returned by a dependent upstream service.
 *
 * Unlike generic Error instances, this error carries HTTP response information
 * that can be safely propagated back through the API layer.
 *
 * @property statusCode
 * HTTP status code to return to the API client.
 *
 * @property payload
 * Structured error payload returned by the upstream dependency.
 */
export class UpstreamServiceError extends Error {
  constructor(
    readonly statusCode: number,
    readonly payload: unknown,
    message = "Upstream service error",
  ) {
    super(message);
  }
}

/**
 * Converts service-layer exceptions into HTTP responses.
 *
 * Known upstream failures preserve their original status code and payload.
 * Unknown failures are mapped to generic availability or timeout responses.
 *
 * @param res
 * Express response object used to send the HTTP response.
 *
 * @param error
 * Exception thrown during service execution.
 *
 * @param messages
 * Service-specific timeout and unavailable messages.
 */
export function sendServiceError(
  res: Response,
  error: unknown,
  messages: {
    timedOut: string;
    unavailable: string;
  },
): void {
  if (error instanceof UpstreamServiceError) {
    res.status(error.statusCode).json(error.payload);
    return;
  }

  const timedOut = isTimeoutError(error);
  res.status(timedOut ? 504 : 503).json({
    error: timedOut ? messages.timedOut : messages.unavailable,
  });
}
