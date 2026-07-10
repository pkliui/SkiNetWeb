import { useEffect, useState } from "react";
import type { Metrics } from "./ResultsGrid";

type CaseReport = {
  summary: string;
  observations: string[];
  qualityChecks: string[];
  promptTrace: {
    mode: "llm" | "deterministic-fallback";
    model: string;
    retrievedContext: string[];
  };
};

type Props = {
  selectedFile: File | null;
  metrics: Metrics | null;
  resultReady: boolean;
};

const CaseReportPanel = ({ selectedFile, metrics, resultReady }: Props) => {
  const [report, setReport] = useState<CaseReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canGenerate = Boolean(selectedFile && metrics && resultReady && !isLoading);

  useEffect(() => {
    setReport(null);
    setError(null);
  }, [selectedFile, resultReady]);

  const generateReport = async () => {
    if (!selectedFile || !metrics) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/case-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fileName: selectedFile.name,
          imageType: selectedFile.type,
          imageSizeBytes: selectedFile.size,
          metrics,
        }),
      });

      if (!response.ok) throw new Error("Report generation failed");
      setReport(await response.json() as CaseReport);
    } catch {
      setError("Could not generate the AI report. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="case-report-panel" aria-label="AI case report">
      <div className="case-report-header">
        <div>
          <h2>AI Segmentation Report</h2>
          <p>Grounded LLM summary with prompt context, quality gates, and safety controls.</p>
        </div>
        <button className="btn-primary" onClick={generateReport} disabled={!canGenerate}>
          {isLoading ? "Generating..." : "Generate report"}
        </button>
      </div>

      {!resultReady && (
        <div className="case-report-placeholder">Run segmentation first to unlock the grounded report workflow.</div>
      )}

      {error && <p className="error-message">{error}</p>}

      {report && (
        <div className="case-report-content">
          <div className="case-report-summary">
            <span className="case-report-badge">
              {report.promptTrace.mode === "llm" ? "LLM" : "Fallback"} · {report.promptTrace.model}
            </span>
            <p>{report.summary}</p>
          </div>

          <ReportList title="Observations" items={report.observations} />
          <ReportList title="Quality checks" items={report.qualityChecks} />

          <details className="prompt-trace">
            <summary>Prompt grounding</summary>
            <ul>
              {report.promptTrace.retrievedContext.map((item) => (
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
