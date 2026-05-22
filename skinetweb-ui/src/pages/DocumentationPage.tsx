const DOCS_URL = "https://pkliui.github.io/SkiNet/";

const DocumentationPage = () => (
  <div className="docs-frame-container">
    <iframe
      src={DOCS_URL}
      title="SkiNet Documentation"
      className="docs-frame"
      sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
    />
  </div>
);

export default DocumentationPage;
