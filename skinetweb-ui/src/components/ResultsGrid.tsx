import React, { useEffect, useRef, useState } from "react";

type Props = {
  previewUrl: string | null;
  resultUrl: string | null;
  gtMaskUrl: string | null;
  onMetricsChange?: (metrics: Metrics | null) => void;
};

export type Metrics = {
  predAreaPct: number;
  dice?: number;
  iou?: number;
  sensitivity?: number;
  specificity?: number;
};

const CANVAS_STYLE = { width: "100%", height: "100%", objectFit: "contain" as const, borderRadius: 8 };

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

/** Rasterise a mask image to a boolean array at (w × h). */
function maskToBinary(mask: HTMLImageElement, w: number, h: number): Uint8Array {
  const off = document.createElement("canvas");
  off.width = w; off.height = h;
  const ctx = off.getContext("2d")!;
  // w/h are the caller's EXIF-corrected original.naturalWidth/naturalHeight (see
  // ContourOverlay below), which only match the backend mask's own dimensions
  // because postprocess (skinet-service/main.py) sized its canvas from the same
  // EXIF-corrected orientation. drawImage doesn't validate that — a mismatch here
  // silently stretches the mask into the wrong aspect ratio instead of erroring.
  ctx.drawImage(mask, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);
  const bin = new Uint8Array(w * h);
  for (let i = 0; i < bin.length; i++) bin[i] = data[i * 4] > 128 ? 1 : 0;
  return bin;
}

/**
 * Draw contour lines of a binary mask onto ctx.
 * A pixel is on the contour when it is foreground and has at least one
 * background neighbour (4-connectivity).
 */
function drawContours(
  ctx: CanvasRenderingContext2D,
  bin: Uint8Array,
  w: number,
  h: number,
  color: string,
  lineWidth = 2,
): void {
  ctx.fillStyle = color;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!bin[y * w + x]) continue;
      const isEdge =
        (x === 0 || !bin[y * w + (x - 1)]) ||
        (x === w - 1 || !bin[y * w + (x + 1)]) ||
        (y === 0 || !bin[(y - 1) * w + x]) ||
        (y === h - 1 || !bin[(y + 1) * w + x]);
      if (isEdge) ctx.fillRect(x, y, lineWidth, lineWidth);
    }
  }
}

function computeMetrics(pred: Uint8Array, gt: Uint8Array | null, total: number): Metrics {
  let predSum = 0;
  let tp = 0, fp = 0, fn = 0, tn = 0;

  for (let i = 0; i < total; i++) {
    const p = pred[i], g = gt ? gt[i] : 0;
    predSum += p;
    if (gt) {
      if (p && g)  tp++;
      if (p && !g) fp++;
      if (!p && g) fn++;
      if (!p && !g) tn++;
    }
  }

  const predAreaPct = (predSum / total) * 100;

  if (!gt) return { predAreaPct };

  const dice        = (2 * tp) / (2 * tp + fp + fn) || 0;
  const iou         = tp / (tp + fp + fn) || 0;
  const sensitivity = tp / (tp + fn) || 0;
  const specificity = tn / (tn + fp) || 0;

  return { predAreaPct, dice, iou, sensitivity, specificity };
}

function MetricBar({ metrics }: { metrics: Metrics }) {
  const fmt = (v: number) => (v * 100).toFixed(1) + "%";
  const items: { label: string; value: string; title: string }[] = [
    { label: "Area", value: metrics.predAreaPct.toFixed(1) + "%", title: "Predicted lesion area as % of image" },
    ...(metrics.dice        != null ? [{ label: "Dice",        value: fmt(metrics.dice),        title: "Dice coefficient (F1)" }] : []),
    ...(metrics.iou         != null ? [{ label: "IoU",         value: fmt(metrics.iou),         title: "Intersection over Union (Jaccard)" }] : []),
    ...(metrics.sensitivity != null ? [{ label: "Sensitivity", value: fmt(metrics.sensitivity), title: "Recall — fraction of GT lesion captured" }] : []),
    ...(metrics.specificity != null ? [{ label: "Specificity", value: fmt(metrics.specificity), title: "Fraction of background correctly excluded" }] : []),
  ];

  return (
    <div className="metric-bar">
      {items.map(({ label, value, title }) => (
        <div key={label} className="metric-item" title={title}>
          <span className="metric-label">{label}</span>
          <span className="metric-value">{value}</span>
        </div>
      ))}
    </div>
  );
}

function ContourOverlay({
  previewUrl, resultUrl, gtMaskUrl,
  onMetricsChange,
}: {
  previewUrl: string;
  resultUrl: string;
  gtMaskUrl?: string;
  onMetricsChange?: (metrics: Metrics | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let cancelled = false;

    (async () => {
      const srcs = [previewUrl, resultUrl, ...(gtMaskUrl ? [gtMaskUrl] : [])];
      const [original, pred, gt] = await Promise.all(srcs.map(loadImage));
      if (cancelled) return;

      const w = original.naturalWidth;
      const h = original.naturalHeight;
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d")!;

      ctx.drawImage(original, 0, 0);

      const predBin = maskToBinary(pred, w, h);
      drawContours(ctx, predBin, w, h, "#00e000");

      let gtBin: Uint8Array | null = null;
      if (gt) {
        gtBin = maskToBinary(gt, w, h);
        drawContours(ctx, gtBin, w, h, "#e00000");
      }

      const nextMetrics = computeMetrics(predBin, gtBin, w * h);
      if (!cancelled) {
        setMetrics(nextMetrics);
        onMetricsChange?.(nextMetrics);
      }
    })();

    return () => {
      cancelled = true;
      onMetricsChange?.(null);
    };
  }, [previewUrl, resultUrl, gtMaskUrl, onMetricsChange]);

  return (
    <>
      <canvas ref={canvasRef} style={CANVAS_STYLE} />
      {metrics && <MetricBar metrics={metrics} />}
    </>
  );
}

const ResultsGrid = ({ previewUrl, resultUrl, gtMaskUrl, onMetricsChange }: Props) => {
  if (!previewUrl) return null;

  const overlayTitle = gtMaskUrl
    ? <>Contours <span className="legend"><span className="legend-green" />predicted &nbsp;<span className="legend-red" />ground truth</span></>
    : "Predicted contour";

  return (
    <div className="results-grid">
      <div className="result-card">
        <h2>Original</h2>
        <img src={previewUrl} alt="Original lesion" />
      </div>

      <div className="result-card">
        <h2>{overlayTitle}</h2>
        {resultUrl ? (
          <ContourOverlay
            previewUrl={previewUrl}
            resultUrl={resultUrl}
            gtMaskUrl={gtMaskUrl ?? undefined}
            onMetricsChange={onMetricsChange}
          />
        ) : (
          <div className="result-placeholder">
            <span>Press Analyse to segment</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default ResultsGrid;
