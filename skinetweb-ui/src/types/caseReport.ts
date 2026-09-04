import type { Metrics } from "../components/ResultsGrid";

/** Mirrors `reporting.models.ReportMode` (skinet-service). */
export type CaseReportMode = "llm" | "deterministic-fallback";

/** Mirrors `reporting.models.ReportProviderName` (skinet-service). */
export type CaseReportProvider = "mistral" | "openrouter" | "local";

/**
 * Audit metadata describing how a report was produced.
 *
 * Mirrors `reporting.models.ReportMetadata` (skinet-service). Fields are
 * camelCase here to match the aliases Pydantic serializes to
 * (e.g. `latency_ms` -> `latencyMs`).
 */
export type ReportMetadata = {
  mode: CaseReportMode;
  model: string;
  provider: CaseReportProvider;
  latencyMs: number;
  context: string[];
  fallbackReason?: string | null;
};

/**
 * The AI case report shown in the report panel.
 *
 * Mirrors `reporting.models.CaseReport` (skinet-service), the
 * `response_model` FastAPI validates the `/case-report` response against.
 */
export type CaseReport = {
  summary: string;
  observations: string[];
  qualityChecks: string[];
  reportMetadata: ReportMetadata;
};

/**
 * Request body sent to `/api/case-report` (proxied on to FastAPI's
 * `/case-report`).
 *
 * Mirrors `reporting.models.CaseReportRequest` (skinet-service). Built by
 * `buildCaseReportRequest` in `useCaseReport.ts` from the selected file and
 * the segmentation metrics already held in UI state.
 */
export type CaseReportRequest = {
  fileName: string;
  metrics: Metrics;
};

/**
 * Live readiness of the configured LLM provider.
 *
 * Mirrors `reporting.models.ProviderStatus` (skinet-service), returned by
 * `GET /api/case-report/status` (proxied on to FastAPI's
 * `GET /case-report/status`).
 */
export type ProviderStatus = {
  llmConfigured: boolean;
  reachable: boolean;
  reason?: string | null;
};
