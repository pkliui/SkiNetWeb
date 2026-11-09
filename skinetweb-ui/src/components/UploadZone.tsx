/**
 * UploadZone
 *
 * Drag-and-drop / click-to-browse file picker for skin lesion images.
 *
 * The component is intentionally stateless with respect to the selected file —
 * the parent (via useSegmentation) owns that state so the rest of the UI can
 * react to it. The only local state is the transient drag-over highlight.
 */

import React, { useState } from "react";
import { ALLOWED_IMAGE_MIME_TYPES } from "../types/upload";
import { urlToFile } from "../utils/imageUtils";

type Props = {
  /** Currently selected file, or null if none has been chosen yet. */
  selectedFile: File | null;
  /** Ref to the hidden <input type="file"> — owned here, forwarded from the hook.
   *  React 18 types useRef<T>(null) as RefObject<T | null>. */
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileSelect: (file: File) => void;
};

const UploadZone = ({ selectedFile, fileInputRef, onFileSelect }: Props) => {
  // Tracks whether a dragged file is hovering over the zone (visual feedback only)
  const [isDragging, setIsDragging] = useState(false);

  const handleDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    setIsDragging(false);

    const exampleUrl = event.dataTransfer.getData("x-example-url");
    if (exampleUrl) {
      try {
        const filename = exampleUrl.split("/").pop() ?? "example.png";
        onFileSelect(await urlToFile(exampleUrl, filename));
      } catch {
        console.error("Failed to load example image:", exampleUrl);
      }
      return;
    }

    const file = event.dataTransfer.files[0];
    if (file) onFileSelect(file);
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) onFileSelect(file);
  };

  return (
    <div
      className={`upload-zone ${isDragging ? "dragging" : ""} ${selectedFile ? "has-file" : ""}`}
      onClick={() => fileInputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      role="button"
      aria-label="Upload image"
    >
      {selectedFile ? (
        /* Show the chosen filename once a file is selected */
        <span className="upload-filename">{selectedFile.name}</span>
      ) : (
        /* Default idle state */
        <>
          <span className="upload-icon">📁</span>
          <span className="upload-hint">Drop an image here or click to browse</span>
        </>
      )}

      {/* Hidden native file input — triggered programmatically on zone click */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_IMAGE_MIME_TYPES.join(",")}
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
    </div>
  );
};

export default UploadZone;
