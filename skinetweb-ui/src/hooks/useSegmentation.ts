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
  previewUrl: string | null;
  resultUrl: string | null;
  gtMaskUrl: string | null;    // object URL for an optional ground-truth mask
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
  const [gtMaskUrl, setGtMaskUrl]       = useState<string | null>(null);
  const [isLoading, setIsLoading]       = useState(false);
  const [error, setError]               = useState<string | null>(null);

  // Ref forwarded to the hidden <input type="file"> inside UploadZone
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** Called whenever the user picks or drops one or more files.
   *  If a second file with "_lesion" in its name is present it is treated as the GT mask. */
  const onFileSelect = (fileOrFiles: File | File[]) => {
    const files = Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles];
    const imageFile = files.find(f => !f.name.includes("_lesion")) ?? files[0];
    const gtFile    = files.find(f =>  f.name.includes("_lesion")) ?? null;

    setSelectedFile(imageFile);
    setResultUrl(null);
    setError(null);
    setPreviewUrl(URL.createObjectURL(imageFile));
    setGtMaskUrl(gtFile ? URL.createObjectURL(gtFile) : null);
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
        // A 413 comes from one of two places:
        // - Express: the file is over MAX_UPLOAD_BYTES (10 MiB).
        // - nginx: the whole request is over client_max_body_size (11 MB), so Express never sees it.
        // Both send JSON whose `error` names the limit (nginx via the error_page in
        // nginx/default.conf). The generic text is a safety net so the user always
        // gets a message when a 413 body isn't that JSON: e.g. Cloudflare, in front
        // of nginx, rejects bodies over its own limit (100 MB on the free plan) with
        // an HTML page, and neither nginx nor Express ever sees the request.
        if (response.status === 413) {
          const err = await response.json().catch(() => null) as { error?: string } | null;
          setError(err?.error ?? "Image is too large. Please use a smaller photo.");
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
    setGtMaskUrl(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return {
    selectedFile, previewUrl, resultUrl, gtMaskUrl, isLoading, error,
    fileInputRef, onFileSelect, onSubmit, onReset,
  };
};
