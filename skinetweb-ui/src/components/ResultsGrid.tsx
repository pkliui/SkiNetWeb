import { useEffect, useRef } from "react";

type Props = {
  previewUrl: string | null;
  resultUrl: string | null;
};

function MaskOverlay({ previewUrl, resultUrl }: { previewUrl: string; resultUrl: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const original = new Image();
    const mask = new Image();
    original.src = previewUrl;
    mask.src = resultUrl;

    let loaded = 0;
    const onLoad = () => {
      loaded += 1;
      if (loaded < 2) return;

      canvas.width = original.naturalWidth;
      canvas.height = original.naturalHeight;

      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(original, 0, 0);

      // Draw mask as a semi-transparent green tint
      // Build a coloured mask on an offscreen canvas, then composite onto the original
      const offscreen = document.createElement("canvas");
      offscreen.width = original.naturalWidth;
      offscreen.height = original.naturalHeight;
      const off = offscreen.getContext("2d")!;
      off.drawImage(mask, 0, 0, original.naturalWidth, original.naturalHeight);

      const imageData = off.getImageData(0, 0, original.naturalWidth, original.naturalHeight);
      const { data } = imageData;
      for (let i = 0; i < data.length; i += 4) {
        const isLesion = data[i] > 128;
        data[i]     = 0;
        data[i + 1] = isLesion ? 220 : 0;
        data[i + 2] = 0;
        data[i + 3] = isLesion ? 50 : 0;
      }
      off.putImageData(imageData, 0, 0);
      // drawImage respects alpha — composites the green tint on top of the original
      ctx.drawImage(offscreen, 0, 0);
    };

    original.onload = onLoad;
    mask.onload = onLoad;
  }, [previewUrl, resultUrl]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", objectFit: "contain", borderRadius: 8 }} />;
}

const ResultsGrid = ({ previewUrl, resultUrl }: Props) => {
  if (!previewUrl) return null;

  return (
    <div className="results-grid">
      {/* Top row: original + overlay */}
      <div className="result-card">
        <h2>Original</h2>
        <img src={previewUrl} alt="Original lesion" />
      </div>

      <div className="result-card">
        <h2>Overlay</h2>
        {resultUrl ? (
          <MaskOverlay previewUrl={previewUrl} resultUrl={resultUrl} />
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
