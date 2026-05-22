/**
 * useSegmentation
 *
 * Custom hook that owns all state and async logic for the segmentation workflow:
 * file selection, API submission, result handling, and reset.
 *
 * Keeping this logic here (rather than in a component) means every component
 * that renders part of the UI stays a pure renderer with no fetch concerns.
 */

import { useState, useRef } from "react";

/** All reactive values exposed to the UI */
type SegmentationState = {
  selectedFile: File | null;
  previewUrl: string | null;   // object URL for the local preview image
  resultUrl: string | null;    // object URL for the segmentation mask returned by the API
  isLoading: boolean;
  error: string | null;
};

/** Callbacks and refs exposed to the UI */
type SegmentationActions = {
  onFileSelect: (file: File) => void;
  onSubmit: () => Promise<void>;
  onReset: () => void;
  // Passed down to UploadZone so it can programmatically open the file picker.
  // React 18 types useRef<T>(null) as RefObject<T | null>.
  fileInputRef: React.RefObject<HTMLInputElement | null>;
};

// Return type is inferred — avoids fighting React 18's RefObject<T | null> variance rules.
export const useSegmentation = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl]     = useState<string | null>(null);
  const [resultUrl, setResultUrl]       = useState<string | null>(null);
  const [isLoading, setIsLoading]       = useState(false);
  const [error, setError]               = useState<string | null>(null);

  // Ref forwarded to the hidden <input type="file"> inside UploadZone
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** Called whenever the user picks or drops a new file. */
  const onFileSelect = (file: File) => {
    setSelectedFile(file);
    setResultUrl(null);   // clear any previous result
    setError(null);
    setPreviewUrl(URL.createObjectURL(file));
  };

  /** Sends the selected image to the backend and stores the returned mask URL. */
  const onSubmit = async () => {
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
        // Nginx body-size limit — give the user an actionable message
        if (response.status === 413) {
          setError("Image is too large. Please use a smaller photo.");
          return;
        }
        const err = await response
          .json()
          .catch(() => ({ error: "Segmentation failed" })) as { error: string };
        setError(err.error ?? "Segmentation failed");
        return;
      }

      const blob = await response.blob();
      setResultUrl(URL.createObjectURL(blob));
    } catch {
      // Network-level failure (no connectivity, CORS, etc.)
      setError("Could not reach the server. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  /** Clears all state and resets the file input so the same file can be re-selected. */
  const onReset = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setResultUrl(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return {
    selectedFile, previewUrl, resultUrl, isLoading, error,
    fileInputRef, onFileSelect, onSubmit, onReset,
  };
};
