import { useEffect, useState } from "react";
import type { ProviderStatus } from "../types/caseReport";

type UseProviderStatusResult = {
  status: ProviderStatus | null;
  isChecking: boolean;
};

/**
 * Fetches LLM provider readiness once on mount, so the report panel can show
 * whether generation is likely to hit the real model before the user waits
 * out a full `/api/case-report` round trip to find out.
 *
 * Deliberately fetched once rather than polled: this answers "is the
 * provider up right now", which is stale the moment a real report request
 * changes provider load anyway, so continuous polling would buy accuracy
 * the UI can't act on while adding background traffic.
 */
export function useProviderStatus(): UseProviderStatusResult {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const response = await fetch("/api/case-report/status");
        if (!response.ok) throw new Error("status check failed");
        const body = (await response.json()) as ProviderStatus;
        if (!cancelled) setStatus(body);
      } catch {
        if (!cancelled) setStatus(null);
      } finally {
        if (!cancelled) setIsChecking(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return { status, isChecking };
}
