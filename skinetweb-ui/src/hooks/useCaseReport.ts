import { useCallback, useEffect, useMemo, useState } from "react";
import type { Metrics } from "../components/ResultsGrid";
import type { CaseReport, CaseReportRequest } from "../types/caseReport";

type UseCaseReportInput = {
  selectedFile: File | null;
  metrics: Metrics | null;
  resultReady: boolean;
};

type UseCaseReportResult = {
  report: CaseReport | null;
  error: string | null;
  isLoading: boolean;
  canGenerate: boolean;
  generateReport: () => Promise<void>;
};

/**
 * Assembles the case-report request body from UI state.
 *
 * This is where the actual values for a case report first exist: the
 * selected `File` and the `Metrics` computed from the segmentation result
 * already held in component state. The returned object becomes `request`
 * in `requestCaseReport`, which is JSON-serialized and POSTed to
 * `/api/case-report`.
 */
function buildCaseReportRequest(file: File, metrics: Metrics): CaseReportRequest {
  return {
    fileName: file.name,
    metrics,
  };
}

function messageForStatus(status: number, detail: string | null): string {
  if (status === 429) return detail ?? "Case report service is busy. Please retry shortly.";
  if (status === 504) return "Case report request timed out. Please try again.";
  if (status === 503) return detail ?? "Case report service is unavailable. Please try again shortly.";
  if (status >= 500) return detail ?? "Case report generation failed. Please try again.";
  return detail ?? "Could not generate the AI report.";
}

/**
 * Sends the case report request to the Express proxy and returns the report.
 *
 * `request` (built by `buildCaseReportRequest`) is JSON-serialized as the
 * POST body to `/api/case-report`. Express forwards it to the inference
 * service (`createCaseReport` in inferenceService.ts), which forwards it to
 * FastAPI's `/case-report` endpoint; the resulting `CaseReport` JSON is
 * relayed back through the same chain to the caller here.
 */
async function requestCaseReport(request: CaseReportRequest): Promise<CaseReport> {
  let response: Response;
  try {
    response = await fetch("/api/case-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new Error("Could not reach the case report service. Check your connection and try again.");
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string; detail?: string } | null;
    const detail = body?.error ?? body?.detail ?? null;
    throw new Error(messageForStatus(response.status, detail));
  }

  return await response.json() as CaseReport;
}

export function useCaseReport({
  selectedFile,
  metrics,
  resultReady,
}: UseCaseReportInput): UseCaseReportResult {
  const [report, setReport] = useState<CaseReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canGenerate = useMemo(
    () => Boolean(selectedFile && metrics && resultReady && !isLoading),
    [selectedFile, metrics, resultReady, isLoading],
  );

  useEffect(() => {
    setReport(null);
    setError(null);
  }, [selectedFile, resultReady]);

  /**
   * Builds the request from current `selectedFile`/`metrics` and POSTs it.
   *
   * Called from `CaseReportPanel` when the user clicks "generate report".
   * Full request path (React state → nginx → Express → FastAPI) is
   * documented in `docs/case-report-request-path.md`.
   */
  const generateReport = useCallback(async () => {
    if (!selectedFile || !metrics) return;

    setIsLoading(true);
    setError(null);

    try {
      setReport(await requestCaseReport(buildCaseReportRequest(selectedFile, metrics)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the AI report. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }, [selectedFile, metrics]);

  return {
    report,
    error,
    isLoading,
    canGenerate,
    generateReport,
  };
}
