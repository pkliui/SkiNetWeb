import { useCaseReport } from "../hooks/useCaseReport";
import { useProviderStatus } from "../hooks/useProviderStatus";
import { describeFallbackReason } from "../types/fallbackReason";
import { describeProviderStatusReason, providerStatusTone } from "../types/providerStatus";
import type { Metrics } from "./ResultsGrid";

type Props = {
  selectedFile: File | null;
  metrics: Metrics | null;
  resultReady: boolean;
};

// Keyed by ProviderStatusTone; the badge shown next to the panel title
// before the user generates a report.
const PROVIDER_STATUS_LABEL = {
  ready: "LLM ready",
  degraded: "LLM reachable",
  down: "LLM unavailable",
} as const;

const CaseReportPanel = ({ selectedFile, metrics, resultReady }: Props) => {
  const { report, error, isLoading, canGenerate, generateReport } = useCaseReport({
    selectedFile,
    metrics,
    resultReady,
  });
  const { status: providerStatus, isChecking: isCheckingProvider } = useProviderStatus();

  return (
    <section className="case-report-panel" aria-label="AI case report">
      <div className="case-report-header">
        <div>
          <h2>LLM Segmentation Summary</h2>
          {!isCheckingProvider && providerStatus && (
            <span
              className={`provider-status-badge provider-status-badge--${providerStatusTone(providerStatus)}`}
              title={providerStatus.reason ? describeProviderStatusReason(providerStatus.reason) : undefined}
            >
              {PROVIDER_STATUS_LABEL[providerStatusTone(providerStatus)]}
            </span>
          )}
        </div>
        <button className="btn-primary" onClick={generateReport} disabled={!canGenerate}>
          {isLoading ? "Generating..." : "Generate LLM summary"}
        </button>
      </div>

      {!resultReady && (
        <div className="case-report-placeholder">Run segmentation first to unlock the report workflow.</div>
      )}

      {error && <p className="error-message">{error}</p>}

      {report && (
        <div className="case-report-content">
          <div className="case-report-summary">
            <span
              className={
                report.reportMetadata.mode === "llm"
                  ? "case-report-badge"
                  : "case-report-badge case-report-badge--fallback"
              }
            >
              {report.reportMetadata.mode === "llm" ? "LLM" : "Fallback"} · {report.reportMetadata.provider} ·{" "}
              {report.reportMetadata.model} · {report.reportMetadata.latencyMs}ms
            </span>
            <p>{report.summary}</p>
            {report.reportMetadata.fallbackReason && (
              <p className="case-report-fallback" role="status">
                {describeFallbackReason(report.reportMetadata.fallbackReason)}
              </p>
            )}
          </div>

          <ReportList title="Observations" items={report.observations} />
          <ReportList title="Quality checks" items={report.qualityChecks} />

          <details className="prompt-trace">
            <summary>Prompt grounding</summary>
            <ul>
              {report.reportMetadata.context.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
};

function ReportList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <div className="case-report-section">
      <h3>{title}</h3>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

export default CaseReportPanel;
