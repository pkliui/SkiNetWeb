import type { ProviderStatus } from "./caseReport";

/**
 * Human-readable copy for `ProviderStatus.reason` slugs.
 *
 * Mirrors the reasons `reporting/status.py`'s `check_provider_status` (and
 * `main.py`'s `case_report_status` for the unconfigured case) can return.
 * `http-*` is matched by prefix because the status code is interpolated
 * into the slug (`http-401`, `http-503`, ...), making it unenumerable.
 */
const REASON_COPY: Record<string, string> = {
  "llm-not-configured": "No AI model is configured for this deployment.",
  "invalid-api-key": "The configured API key was rejected by the provider.",
  "network-error": "The AI provider could not be reached.",
  "invalid-model": "The configured model is not served by the provider.",
  "model-check-failed": "The provider is reachable, but its model list could not be confirmed.",
};

/**
 * Maps a `ProviderStatus.reason` slug to a sentence a user can read.
 *
 * Falls back to the raw slug for an unrecognized reason so a new one added
 * on the Python side still surfaces something, rather than going silent.
 */
export function describeProviderStatusReason(reason: string): string {
  return REASON_COPY[reason] ?? (reason.startsWith("http-") ? `The provider returned an error (${reason.slice("http-".length)}).` : reason);
}

export type ProviderStatusTone = "ready" | "degraded" | "down";

/**
 * Classifies a `ProviderStatus` into a badge tone.
 *
 * "degraded" is `reachable: true` with a non-null `reason` — i.e.
 * `model-check-failed`, where the provider itself is up but one precision
 * check on it wasn't confirmed. Report generation still hits the real LLM
 * in that case, so it reads as a caveat rather than an outage.
 */
export function providerStatusTone(status: ProviderStatus): ProviderStatusTone {
  if (!status.reachable) return "down";
  if (status.reason) return "degraded";
  return "ready";
}
