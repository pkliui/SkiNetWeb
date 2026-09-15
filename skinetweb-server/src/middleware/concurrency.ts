import type { NextFunction, Request, RequestHandler, Response } from "express";

import { ConcurrencyLimiter } from "../utils/concurrency.js";

/**
 * Creates Express middleware that limits the number of concurrent requests
 * entering a protected service path.
 *
 * This middleware implements backpressure by rejecting requests when the
 * configured concurrency limit has been reached. It is intended to protect
 * resource-intensive operations such as image segmentation or report
 * generation from excessive parallel execution.
 *
 * The limiter instance is created once when the middleware is constructed and
 * shared by all requests handled by that middleware. This ensures concurrency
 * accounting is maintained across the lifetime of the application.
 *
 * Request lifecycle:
 *
 * 1. Incoming request attempts to acquire a concurrency slot.
 * 2. If a slot is available:
 *    - The request proceeds to the next middleware.
 *    - A cleanup callback is registered to release the slot when the response
 *      completes or the connection closes.
 *
 * 3. If no slot is available:
 *    - The request is rejected immediately with HTTP 429.
 *
 * Resource cleanup:
 * - The acquired slot is released on both successful response completion
 *   (`finish`) and aborted connections (`close`) to prevent leaked capacity.
 *
 * @param maxConcurrent Maximum number of requests allowed to execute
 *                      concurrently.
 * @param busyMessage Error message returned when the concurrency limit is
 *                    exceeded.
 *
 * @returns Express middleware implementing concurrency limiting.
 */
export function createConcurrencyMiddleware(
    maxConcurrent: number,
    busyMessage: string
  ): RequestHandler {
  const limiter = new ConcurrencyLimiter(maxConcurrent);

  return (_req: Request, res: Response, next: NextFunction): void => {
    // Attempt to acquire a concurrency slot.
    // Return the release callback if successful.
    const release = limiter.tryAcquire();
    if (!release) {
      res.status(429).json({ error: busyMessage });
      return;
    }

    // Register cleanup callbacks to release the slot when the response is
    // complete or the connection is closed.
    const cleanup = (): void => {
      res.off("finish", cleanup);
      res.off("close", cleanup);
      release();
    };

    res.once("finish", cleanup);
    res.once("close", cleanup);
    next();
  };
}
