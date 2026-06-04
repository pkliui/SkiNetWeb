import React, { useEffect, useState } from "react";
import { urlToFile } from "../utils/imageUtils";

type LesionExample = { id: string; label: string; src: string; gtSrc: string };
type LesionGroup   = { group: string; items: LesionExample[] };

const LESION_GROUPS: LesionGroup[] = [
  {
    group: "Malignant",
    items: [
      { id: "IMD285_melanoma",          label: "Melanoma",          src: "/examples/IMD285_melanoma.png",          gtSrc: "/examples/IMD285_lesion.png" },
    ],
  },
  {
    group: "Benign",
    items: [
      { id: "ISIC_0012092",             label: "ISIC 2017 test 1",  src: "/examples/ISIC_0012092.png",             gtSrc: "/examples/ISIC_0012092_lesion.png" },
      { id: "IMD002_atypical_nevus",    label: "Atypical nevus",    src: "/examples/IMD002_atypical_nevus.png",    gtSrc: "/examples/IMD002_lesion.png" },
      { id: "IMD004_atypical_nevus",    label: "Atypical nevus",    src: "/examples/IMD004_atypical_nevus.png",    gtSrc: "/examples/IMD004_lesion.png" },
      { id: "IMD016_common_nevus",      label: "Common nevus",      src: "/examples/IMD016_common_nevus.png",      gtSrc: "/examples/IMD016_lesion.png" },
      { id: "IMD025_common_nevus",      label: "Common nevus",      src: "/examples/IMD025_common_nevus.png",      gtSrc: "/examples/IMD025_lesion.png" },
      { id: "IMD078_intradermal_nevus", label: "Intradermal nevus", src: "/examples/IMD078_intradermal_nevus.png", gtSrc: "/examples/IMD078_lesion.png" },
    ],
  },
];

type IsicExample = { imageSrc: string; gtSrc: string | null; label: string };

type Props = { onFileSelect: (files: File | File[]) => void };

const ExampleGallery = ({ onFileSelect }: Props) => {
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

  return (
    <aside className="gallery-sidebar">
      <p className="gallery-title">Examples</p>
      <p className="gallery-hint">Drag to zone or click</p>

      <div className="gallery-group">
        <div className="gallery-group-header">
          <p className="gallery-group-label">ISIC 2017 Test</p>
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

      {LESION_GROUPS.map(({ group, items }) => (
        <div key={group} className="gallery-group">
          <p className="gallery-group-label">{group}</p>
          <ul className="gallery-list">
            {items.map(({ id, label, src, gtSrc }) => (
              <li key={id} className="gallery-item">
                <img
                  src={src}
                  alt={label}
                  className="gallery-thumb"
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData("x-example-url", src)}
                  onClick={() => select(src, gtSrc, `${id}.png`)}
                />
                <span className="gallery-label">{label}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </aside>
  );
};

export default ExampleGallery;
