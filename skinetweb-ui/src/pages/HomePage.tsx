import { useEffect, useState } from "react";
import ResultsGrid from "../components/ResultsGrid";
import UploadZone from "../components/UploadZone";
import ExampleGallery from "../examples/ExampleGallery";
import { useSegmentation } from "../hooks/useSegmentation";

const MOBILE_BREAKPOINT = 620;

const HomePage = () => {
  const {
    selectedFile,
    previewUrl,
    resultUrl,
    gtMaskUrl,
    isLoading,
    error,
    fileInputRef,
    onFileSelect,
    onSubmit,
    onReset,
  } = useSegmentation();

  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches
  );

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <div className="app-container">
      {!isMobile && <ExampleGallery onFileSelect={onFileSelect} variant="sidebar" />}

      <div className="main-column">
        <h1 className="app-title">SkiNet</h1>
        <p className="app-subtitle">Skin lesion segmentation</p>

        <div className="home-description">
          <p>
            SkiNet is a deep learning tool for automatic segmentation of skin lesions in dermoscopy images,
            trained on ISIC 2017 dataset.

            Upload a dermoscopic image to receive a precise lesion mask and an overlay highlighting the
            segmented region.
          </p>
          <div className="home-steps">
            <div className="home-step">
              <span className="home-step-number">1</span>
              <span>Upload a dermoscopy image{!isMobile && " or pick one from the examples on the left"}</span>
            </div>
            <div className="home-step">
              <span className="home-step-number">2</span>
              <span>Click <strong>Analyse</strong> to run the segmentation model</span>
            </div>
            <div className="home-step">
              <span className="home-step-number">3</span>
              <span>Review the overlay and binary mask</span>
            </div>
          </div>
        </div>

        <UploadZone
          selectedFile={selectedFile}
          fileInputRef={fileInputRef}
          onFileSelect={onFileSelect}
        />

        {isMobile && <ExampleGallery onFileSelect={onFileSelect} variant="accordion" />}

        {selectedFile && (
          <div className="action-row">
            <button className="btn-primary" onClick={onSubmit} disabled={isLoading}>
              {isLoading ? "Analysing…" : "Analyse"}
            </button>
            <button className="btn-secondary" onClick={onReset} disabled={isLoading}>
              Reset
            </button>
          </div>
        )}

        {error && <p className="error-message">{error}</p>}

        <ResultsGrid previewUrl={previewUrl} resultUrl={resultUrl} gtMaskUrl={gtMaskUrl} />
      </div>
    </div>
  );
};

export default HomePage;
