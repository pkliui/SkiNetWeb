import React, { useEffect, useState } from "react";
import { urlToFile } from "../utils/imageUtils";

type IsicExample = { imageSrc: string; gtSrc: string | null; label: string };

type Props = {
  onFileSelect: (files: File | File[]) => void;
  variant?: "sidebar" | "accordion";
};

const ExampleGallery = ({ onFileSelect, variant = "sidebar" }: Props) => {
  const [isicExamples, setIsicExamples] = useState<IsicExample[]>([]);
  const [isicLoading, setIsicLoading]   = useState(false);
  const [fetchKey, setFetchKey]         = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsicLoading(true);
    fetch("/api/random-examples?count=5")
      .then(r => r.ok ? r.json() as Promise<IsicExample[]> : [])
      .then(data => { if (!cancelled) setIsicExamples(data); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setIsicLoading(false); });
    return () => { cancelled = true; };
  }, [fetchKey]);

  const select = async (src: string, gtSrc: string | null, filename: string) => {
    try {
      if (gtSrc) {
        const [imageFile, gtFile] = await Promise.all([
          urlToFile(src, filename),
          urlToFile(gtSrc, filename.replace(/\.[^.]+$/, "_lesion.png")),
        ]);
        onFileSelect([imageFile, gtFile]);
      } else {
        onFileSelect(await urlToFile(src, filename));
      }
    } catch {
      console.error("Failed to load example image:", src);
    }
  };

  const galleryContent = (
    <div className="gallery-group">
      <div className="gallery-group-header">
        {variant === "sidebar" && (
          <p className="gallery-group-label">ISIC 2017 Test</p>
        )}
        <button
          className={`gallery-reload-btn${isicLoading ? " gallery-reload-btn--spinning" : ""}`}
          onClick={() => setFetchKey((k: number) => k + 1)}
          disabled={isicLoading}
          title="Load new random examples"
          aria-label="Reload random examples"
        >
          ↻
        </button>
      </div>
      {isicLoading && isicExamples.length === 0 ? (
        <ul className="gallery-list">
          {[0, 1, 2, 3, 4].map(i => (
            <li key={i} className="gallery-item">
              <div className="gallery-thumb gallery-thumb--skeleton" />
            </li>
          ))}
        </ul>
      ) : (
        <ul className="gallery-list">
          {isicExamples.map((ex: IsicExample) => (
            <li key={ex.label} className="gallery-item">
              <img
                src={ex.imageSrc}
                alt={ex.label}
                className="gallery-thumb"
                draggable
                onDragStart={(e) => e.dataTransfer.setData("x-example-url", ex.imageSrc)}
                onClick={() => select(ex.imageSrc, ex.gtSrc, `${ex.label}.jpg`)}
              />
              <span className="gallery-label">{ex.label.replace("ISIC_", "")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (variant === "accordion") {
    return (
      <details className="gallery-accordion">
        <summary className="gallery-accordion-toggle">
          <span>Try an example image</span>
          <span className="gallery-accordion-arrow">▾</span>
        </summary>
        <div className="gallery-accordion-body">
          {galleryContent}
        </div>
      </details>
    );
  }

  return (
    <aside className="gallery-sidebar">
      <p className="gallery-title">Examples</p>
      <p className="gallery-hint">Drag to zone or click</p>
      {galleryContent}
    </aside>
  );
};

export default ExampleGallery;
