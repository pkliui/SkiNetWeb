/**
 * Human-readable copy for the `reportMetadata.fallbackReason` slugs.
 *
 * The API returns machine-readable slugs (`llm-timeout`, `llm-http-401`, ...)
 * produced by `skinet-service/reporting/client.py` and `generator.py`. Showing
 * them raw asks the reader to decode an internal identifier, and worse, reads
 * as an error when the report beside it is perfectly valid.
 *
 * Every message must make the same two points: what went wrong with the model,
 * and that the report's numbers are still exact — only the wording is
 * templated, because the deterministic builder derives it from the same
 * segmentation metrics.
 */

const FALLBACK_REASON_COPY: Record<string, string> = {
  "llm-timeout":
    "The AI model took too long to respond, so this report was generated directly from your segmentation metrics.",
  "llm-not-configured":
    "No AI model is configured for this deployment, so this report was generated directly from your segmentation metrics.",
  "llm-invalid-json":
    "The AI model returned a response that did not match the expected report format, so this report was generated directly from your segmentation metrics.",
  // Distinct from `llm-invalid-json`: there the model replied and its output
  // was malformed; here the reply never came from the model at all, so the
  // copy points at the service rather than blaming the model.
  "llm-invalid-response":
    "The AI service returned an unreadable reply, so this report was generated directly from your segmentation metrics.",
  "llm-network-error":
    "The AI model could not be reached, so this report was generated directly from your segmentation metrics.",
  "llm-empty-response":
    "The AI model returned an empty response, so this report was generated directly from your segmentation metrics.",
  "llm-output-truncated":
    "The AI model's response was cut short, so this report was generated directly from your segmentation metrics.",
  "llm-content-filtered":
    "The AI model's response was blocked by a content filter, so this report was generated directly from your segmentation metrics.",
  "llm-refusal":
    "The AI model declined to answer, so this report was generated directly from your segmentation metrics.",
  "llm-request-failed":
    "The request to the AI model failed, so this report was generated directly from your segmentation metrics.",
  "llm-unavailable":
    "The AI model was unavailable, so this report was generated directly from your segmentation metrics.",
};

const GENERIC_FALLBACK_COPY =
  "The AI model could not complete this report, so it was generated directly from your segmentation metrics.";

const METRICS_ARE_EXACT = "The measurements are exact; only the wording is templated.";

/**
 * Maps a fallback reason slug to a sentence a clinician-facing user can read.
 *
 * Falls back to generic copy for unknown slugs so a new reason added on the
 * Python side degrades to a vague-but-true message rather than a blank line.
 * `llm-http-*` is matched by prefix because the status code is interpolated
 * into the slug (`llm-http-401`, `llm-http-503`, ...), making it unenumerable.
 */
export function describeFallbackReason(reason: string): string {
  const known =
    FALLBACK_REASON_COPY[reason] ??
    (reason.startsWith("llm-http-")
      ? `The AI model returned an error (${reason.slice("llm-http-".length)}), so this report was generated directly from your segmentation metrics.`
      : GENERIC_FALLBACK_COPY);

  return `${known} ${METRICS_ARE_EXACT}`;
}
