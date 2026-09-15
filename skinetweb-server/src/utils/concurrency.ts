/**
 * Lightweight concurrency limiter implementing a semaphore-like mechanism.
 *
 * The limiter tracks the number of currently active operations and allows
 * callers to reserve execution slots up to a configured maximum concurrency.
 *
 * Slot acquisition is non-blocking:
 * - If capacity is available, `tryAcquire()` increments the active count and
 *   returns a release callback.
 * - If the concurrency limit has been reached, `tryAcquire()` returns `null`
 *   immediately instead of queueing the request.
 *
 * Usage pattern:
 *
 *   const release = limiter.tryAcquire();
 *
 *   if (!release) {
 *     // reject or defer the operation
 *   }
 *
 *   // Perform the protected operation.
 *
 *   release(); // return the slot when the operation completes
 *
 * The returned release callback is idempotent, meaning it can safely be
 * invoked multiple times without decrementing the active counter more than
 * once. This protects the limiter from duplicate cleanup paths in asynchronous
 * workflows.
 *
 * The limiter is intended to protect resource-intensive workloads such as
 * machine learning inference, external service calls, database operations,
 * or CPU-heavy processing where uncontrolled parallel execution could exhaust
 * available resources.
 */
export class ConcurrencyLimiter {
  private active = 0;

  constructor(private readonly maxActive: number) {}

  tryAcquire(): (() => void) | null {
    if (this.active >= this.maxActive) return null;

    this.active += 1;
    let released = false;

    return () => {
      if (released) return;
      released = true;
      this.active -= 1;
    };
  }
}
