import React, { useState, useRef } from "react";
import "./App.css";

const App = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const applyFile = (file: File) => {
    setSelectedFile(file);
    setResultUrl(null);
    setError(null);
    setPreviewUrl(URL.createObjectURL(file));
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) applyFile(file);
  };

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) applyFile(file);
  };

  const handleSubmit = async () => {
    if (!selectedFile) return;
    setIsLoading(true);
    setError(null);
    setResultUrl(null);

    try {
      const formData = new FormData();
      formData.append("image", selectedFile);

      const response = await fetch("/api/segment", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json() as { error: string };
        setError(err.error ?? "Segmentation failed");
        return;
      }

      const blob = await response.blob();
      setResultUrl(URL.createObjectURL(blob));
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setResultUrl(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="app-container">
      <h1 className="app-title">SkiNet</h1>
      <p className="app-subtitle">Skin lesion segmentation</p>

      <div
        className={`upload-zone ${isDragging ? "dragging" : ""} ${selectedFile ? "has-file" : ""}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        {selectedFile ? (
          <span className="upload-filename">{selectedFile.name}</span>
        ) : (
          <>
            <span className="upload-icon">📁</span>
            <span className="upload-hint">Drop an image here or click to browse</span>
          </>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
      </div>

      {selectedFile && (
        <div className="action-row">
          <button className="btn-primary" onClick={handleSubmit} disabled={isLoading}>
            {isLoading ? "Analysing…" : "Analyse"}
          </button>
          <button className="btn-secondary" onClick={handleReset} disabled={isLoading}>
            Reset
          </button>
        </div>
      )}

      {error && <p className="error-message">{error}</p>}

      {(previewUrl || resultUrl) && (
        <div className="results-grid">
          {previewUrl && (
            <div className="result-card">
              <h2>Original</h2>
              <img src={previewUrl} alt="Original lesion" />
            </div>
          )}
          {resultUrl && (
            <div className="result-card">
              <h2>Segmentation mask</h2>
              <img src={resultUrl} alt="Segmentation mask" />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default App;
