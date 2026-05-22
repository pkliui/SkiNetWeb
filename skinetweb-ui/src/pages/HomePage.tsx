import UploadZone     from "../components/UploadZone";
import ResultsGrid    from "../components/ResultsGrid";
import ExampleGallery from "../examples/ExampleGallery";
import { useSegmentation } from "../hooks/useSegmentation";

const HomePage = () => {
  const {
    selectedFile,
    previewUrl,
    resultUrl,
    isLoading,
    error,
    fileInputRef,
    onFileSelect,
    onSubmit,
    onReset,
  } = useSegmentation();

  return (
    <div className="app-container">
      <ExampleGallery onFileSelect={onFileSelect} />

      <div className="main-column">
        <h1 className="app-title">SkiNet</h1>
        <p className="app-subtitle">Skin lesion segmentation</p>

        <UploadZone
          selectedFile={selectedFile}
          fileInputRef={fileInputRef}
          onFileSelect={onFileSelect}
        />

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

        <ResultsGrid previewUrl={previewUrl} resultUrl={resultUrl} />
      </div>
    </div>
  );
};

export default HomePage;
