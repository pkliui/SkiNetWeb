/**
 * ResultsGrid
 *
 * Side-by-side display of the original image and the segmentation mask.
 * Renders nothing until at least one URL is available, so the parent
 * doesn't need to gate the render itself.
 */


type Props = {
  /** Object URL for the locally-selected image (available as soon as a file is picked). */
  previewUrl: string | null;
  /** Object URL for the segmentation mask returned by the API (available after a successful submit). */
  resultUrl: string | null;
};

const ResultsGrid = ({ previewUrl, resultUrl }: Props) => {
  if (!previewUrl) return null;

  return (
    <div className="results-grid">
      <div className="result-card">
        <h2>Original</h2>
        <img src={previewUrl} alt="Original lesion" />
      </div>

      <div className="result-card">
        <h2>Segmentation mask</h2>
        {resultUrl ? (
          <img src={resultUrl} alt="Segmentation mask" />
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
