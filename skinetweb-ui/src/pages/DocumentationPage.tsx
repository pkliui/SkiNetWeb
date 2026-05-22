const DocumentationPage = () => (
  <div className="page-container">
    <h1 className="page-title">Documentation</h1>

    <section className="doc-section">
      <h2>Overview</h2>
      <p>
        SkiNet is a deep-learning pipeline for automated skin-lesion segmentation.
        Upload a dermoscopic image and the model returns a binary segmentation mask
        highlighting the lesion boundary.
      </p>
    </section>

    <section className="doc-section">
      <h2>How to use</h2>
      <ol className="doc-list">
        <li>Select an image by dragging it onto the upload zone, clicking to browse, or picking one of the example lesions from the sidebar.</li>
        <li>Click <strong>Analyse</strong> — the server runs the U-Net inference and returns the segmentation mask.</li>
        <li>The original image and the predicted mask are shown side by side in the results panel.</li>
        <li>Click <strong>Reset</strong> to clear the current image and start again.</li>
      </ol>
    </section>

    <section className="doc-section">
      <h2>Supported image formats</h2>
      <p>JPEG, PNG, and BMP images up to 10 MB. The model was trained on dermoscopic images from the ISIC 2017 dataset.</p>
    </section>

    <section className="doc-section">
      <h2>Model</h2>
      <p>
        The segmentation backbone is a <strong>U-Net 2D</strong> encoder–decoder with a ResNet encoder,
        trained to minimise binary cross-entropy + Dice loss on the ISIC 2017 training split.
        Inference runs on the server and typically completes in under two seconds.
      </p>
    </section>

    <section className="doc-section">
      <h2>External links</h2>
      <ul className="doc-link-list">
        <li>
          <a href="https://pkliui.github.io/SkiNet/" target="_blank" rel="noopener noreferrer">
            Full project documentation ↗
          </a>
        </li>
        <li>
          <a href="https://challenge.isic-archive.com/landing/2017/" target="_blank" rel="noopener noreferrer">
            ISIC 2017 Challenge ↗
          </a>
        </li>
      </ul>
    </section>
  </div>
);

export default DocumentationPage;
