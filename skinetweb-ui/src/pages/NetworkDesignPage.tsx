const NETWORK_DESIGN_URL = "https://pkliui.github.io/SkiNet/network_design.html";

const NetworkDesignPage = () => (
  <div className="docs-frame-container">
    <iframe
      src={NETWORK_DESIGN_URL}
      title="SkiNet Network Design"
      className="docs-frame"
      sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
    />
  </div>
);

export default NetworkDesignPage;
