const NetworkDesignPage = () => (
  <div className="page-container">
    <h1 className="page-title">Network Design</h1>

    <section className="doc-section">
      <h2>Architecture — U-Net 2D</h2>
      <p>
        SkiNet uses a symmetric encoder–decoder architecture (U-Net) with skip connections
        that preserve spatial detail lost during downsampling.
      </p>

      <div className="arch-diagram">
        <div className="arch-row">
          <div className="arch-block encoder">Encoder block 1<br /><span>64 ch · 256×256</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">Encoder block 2<br /><span>128 ch · 128×128</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">Encoder block 3<br /><span>256 ch · 64×64</span></div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">Encoder block 4<br /><span>512 ch · 32×32</span></div>
        </div>
        <div className="arch-bottleneck-row">
          <div className="arch-block bottleneck">Bottleneck<br /><span>1024 ch · 16×16</span></div>
        </div>
        <div className="arch-row">
          <div className="arch-block decoder">Decoder block 4<br /><span>512 ch · 32×32</span></div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">Decoder block 3<br /><span>256 ch · 64×64</span></div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">Decoder block 2<br /><span>128 ch · 128×128</span></div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">Decoder block 1<br /><span>64 ch · 256×256</span></div>
        </div>
        <div className="arch-output-row">
          <div className="arch-block output">Output mask<br /><span>1 ch · 256×256 · sigmoid</span></div>
        </div>
      </div>
    </section>

    <section className="doc-section">
      <h2>Key design choices</h2>
      <ul className="doc-list">
        <li><strong>Encoder backbone:</strong> ResNet (pretrained on ImageNet) — provides strong low-level feature extraction with fewer parameters than a from-scratch encoder.</li>
        <li><strong>Skip connections:</strong> concatenate encoder feature maps into the decoder at each resolution level, recovering boundary detail.</li>
        <li><strong>Loss function:</strong> Binary cross-entropy + Dice loss — BCE handles per-pixel accuracy while Dice directly optimises the overlap metric used in evaluation.</li>
        <li><strong>Optimiser:</strong> AdamW with cosine-annealing LR schedule, tuned via Optuna sweep.</li>
        <li><strong>Augmentation:</strong> Random horizontal/vertical flip, rotation, colour jitter — applied only to the training split.</li>
      </ul>
    </section>

    <section className="doc-section">
      <h2>Training setup</h2>
      <table className="info-table">
        <tbody>
          <tr><td>Dataset</td><td>ISIC 2017 (2 000 train / 150 val / 600 test)</td></tr>
          <tr><td>Input size</td><td>256 × 256 px</td></tr>
          <tr><td>Batch size</td><td>8</td></tr>
          <tr><td>Epochs</td><td>100 (early stopping on val Dice)</td></tr>
          <tr><td>Hardware</td><td>2 × GPU (distributed training)</td></tr>
          <tr><td>Framework</td><td>PyTorch + segmentation-models-pytorch</td></tr>
        </tbody>
      </table>
    </section>

    <section className="doc-section">
      <h2>Inference pipeline</h2>
      <ol className="doc-list">
        <li>Image is resized to 256 × 256 and normalised (ImageNet mean/std).</li>
        <li>Forward pass through U-Net; output logits are passed through sigmoid.</li>
        <li>Threshold at 0.5 to produce the binary mask.</li>
        <li>Mask is resized back to the original image resolution before returning.</li>
      </ol>
    </section>
  </div>
);

export default NetworkDesignPage;
