const NetworkDesignPage = () => (
  <div className="page-container">
    <h1 className="page-title">Network Design</h1>

    {/* ── Overview ───────────────────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Architecture — U-Net 2D (custom, from scratch)</h2>
      <p>
        SkiNet is a symmetric encoder–decoder network built entirely from scratch in PyTorch,
        without pre-trained backbones. The encoder path progressively compresses spatial
        resolution while doubling channel depth at each stage. The decoder path mirrors it,
        restoring resolution via transposed convolutions. Skip connections at every resolution
        level carry high-frequency spatial detail from encoder to decoder, preventing
        boundary information from being lost during downsampling.
      </p>
    </section>

    {/* ── Architecture diagram ───────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Architecture diagram</h2>

      <div className="arch-diagram">
        {/* Encoder row */}
        <div className="arch-row">
          <div className="arch-block encoder">
            Encoder 1<br />
            <span>16 ch · 256×256<br />stride 1</span>
          </div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">
            Encoder 2<br />
            <span>32 ch · 128×128<br />stride 2</span>
          </div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">
            Encoder 3<br />
            <span>64 ch · 64×64<br />stride 2</span>
          </div>
          <div className="arch-arrow">→</div>
          <div className="arch-block encoder">
            Encoder 4<br />
            <span>128 ch · 32×32<br />stride 2</span>
          </div>
        </div>

        {/* Bottleneck */}
        <div className="arch-bottleneck-row">
          <div className="arch-block bottleneck">
            Bottleneck (Encoder 5)<br />
            <span>256 ch · 16×16 · stride 2</span>
          </div>
        </div>

        {/* Decoder row */}
        <div className="arch-row">
          <div className="arch-block decoder">
            He2-Merge 4<br />
            <span>128 ch · 32×32</span>
          </div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">
            He2-Merge 3<br />
            <span>64 ch · 64×64</span>
          </div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">
            He2-Merge 2<br />
            <span>32 ch · 128×128</span>
          </div>
          <div className="arch-arrow">←</div>
          <div className="arch-block decoder">
            He2-Merge 1<br />
            <span>16 ch · 256×256</span>
          </div>
        </div>

        {/* Output */}
        <div className="arch-output-row">
          <div className="arch-block output">
            1×1 conv → sigmoid<br />
            <span>1 ch · 256×256 · binary mask</span>
          </div>
        </div>
      </div>

      <p style={{ marginTop: "0.75rem", fontSize: "0.9rem", color: "#666" }}>
        Skip connections (not shown) run from each encoder layer to its
        mirror decoder merge block. Each upsampling step uses a
        transposed convolution (stride 2), restoring the spatial dimensions
        halved by the corresponding encoder stage.
      </p>
    </section>

    {/* ── Block design ───────────────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Block design</h2>

      <h3>Encoder block — Classical (Ronneberger et al., 2015)</h3>
      <p>
        Two sequential Conv2d(3×3) → BatchNorm → ReLU layers per encoder stage.
        The first convolution downsamples (stride 2); the second refines at the
        reduced resolution (stride 1). No residual connection — the original
        UNet design, used as the baseline in the architecture sweep.
      </p>

      {/* ── Encoder block diagram ── */}
      <div style={{ overflowX: "auto", margin: "0.75rem 0 1.25rem" }}>
        <svg viewBox="0 0 540 80" style={{ width: "100%", maxWidth: "540px", display: "block" }}
             aria-label="Classical encoder block data-flow diagram">
          {/* input */}
          <text x="5" y="45" fontSize="13" fontFamily="system-ui,sans-serif" fill="#444" fontStyle="italic">x</text>
          <line x1="19" y1="42" x2="29" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="29,38 37,42 29,46" fill="#666"/>

          {/* Conv 3×3 stride 2 */}
          <rect x="37" y="22" width="90" height="40" rx="4" fill="#dce8f8" stroke="#4a7cc7" strokeWidth="1.3"/>
          <text x="82" y="37" textAnchor="middle" fontSize="11" fontFamily="system-ui,sans-serif" fill="#1a3a6b" fontWeight="600">Conv 3×3</text>
          <text x="82" y="52" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#4a7cc7">stride 2</text>
          <line x1="127" y1="42" x2="137" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="137,38 145,42 137,46" fill="#666"/>

          {/* BN */}
          <rect x="145" y="22" width="38" height="40" rx="4" fill="#d8edd8" stroke="#3a7a3a" strokeWidth="1.3"/>
          <text x="164" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#1a4a1a" fontWeight="600">BN</text>
          <line x1="183" y1="42" x2="193" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="193,38 201,42 193,46" fill="#666"/>

          {/* ReLU */}
          <rect x="201" y="22" width="50" height="40" rx="4" fill="#fde8cc" stroke="#cc7a00" strokeWidth="1.3"/>
          <text x="226" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#7a3a00" fontWeight="600">ReLU</text>
          <line x1="251" y1="42" x2="263" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="263,38 271,42 263,46" fill="#666"/>

          {/* Conv 3×3 stride 1 */}
          <rect x="271" y="22" width="90" height="40" rx="4" fill="#dce8f8" stroke="#4a7cc7" strokeWidth="1.3"/>
          <text x="316" y="37" textAnchor="middle" fontSize="11" fontFamily="system-ui,sans-serif" fill="#1a3a6b" fontWeight="600">Conv 3×3</text>
          <text x="316" y="52" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#4a7cc7">stride 1</text>
          <line x1="361" y1="42" x2="371" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="371,38 379,42 371,46" fill="#666"/>

          {/* BN */}
          <rect x="379" y="22" width="38" height="40" rx="4" fill="#d8edd8" stroke="#3a7a3a" strokeWidth="1.3"/>
          <text x="398" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#1a4a1a" fontWeight="600">BN</text>
          <line x1="417" y1="42" x2="427" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="427,38 435,42 427,46" fill="#666"/>

          {/* ReLU */}
          <rect x="435" y="22" width="50" height="40" rx="4" fill="#fde8cc" stroke="#cc7a00" strokeWidth="1.3"/>
          <text x="460" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#7a3a00" fontWeight="600">ReLU</text>
          <line x1="485" y1="42" x2="497" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="497,38 505,42 497,46" fill="#666"/>

          {/* output */}
          <text x="508" y="47" fontSize="13" fontFamily="system-ui,sans-serif" fill="#444">out</text>
        </svg>
      </div>

      <h3>Decoder block — transposed convolution upsampling</h3>
      <p>
        Each decoder stage begins by doubling the spatial resolution with a single
        transposed convolution, followed by BatchNorm and ReLU. The kernel size is
        set to <code>encoder_kernel × encoder_stride = 3 × 2 = 6</code> rather than
        the more common 2×2, which eliminates the uneven overlap pattern that
        produces checkerboard artefacts in the output mask (Odena et al., 2016).
        The stride of 2 exactly inverts the downsampling applied by the corresponding
        encoder stage. The output of this block is passed directly to the He2 Merge
        block below alongside the skip connection.
      </p>

      {/* ── Decoder block diagram ── */}
      <div style={{ overflowX: "auto", margin: "0.75rem 0 1.25rem" }}>
        <svg viewBox="0 0 480 80" style={{ width: "100%", maxWidth: "480px", display: "block" }}
             aria-label="Decoder upsampling block data-flow diagram">
          {/* input */}
          <text x="5" y="45" fontSize="13" fontFamily="system-ui,sans-serif" fill="#444" fontStyle="italic">x</text>
          <line x1="19" y1="42" x2="29" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="29,38 37,42 29,46" fill="#666"/>

          {/* ConvTranspose2d */}
          <rect x="37" y="16" width="132" height="52" rx="4" fill="#f0e8fe" stroke="#7a44bb" strokeWidth="1.3"/>
          <text x="103" y="34" textAnchor="middle" fontSize="11" fontFamily="system-ui,sans-serif" fill="#3a0a7a" fontWeight="600">ConvTranspose2d</text>
          <text x="103" y="49" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#7a44bb">6×6, stride 2</text>
          <text x="103" y="62" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#7a44bb">spatial ×2, channels ÷2</text>
          <line x1="169" y1="42" x2="179" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="179,38 187,42 179,46" fill="#666"/>

          {/* BN */}
          <rect x="187" y="22" width="38" height="40" rx="4" fill="#d8edd8" stroke="#3a7a3a" strokeWidth="1.3"/>
          <text x="206" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#1a4a1a" fontWeight="600">BN</text>
          <line x1="225" y1="42" x2="235" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="235,38 243,42 235,46" fill="#666"/>

          {/* ReLU */}
          <rect x="243" y="22" width="50" height="40" rx="4" fill="#fde8cc" stroke="#cc7a00" strokeWidth="1.3"/>
          <text x="268" y="47" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#7a3a00" fontWeight="600">ReLU</text>
          <line x1="293" y1="42" x2="305" y2="42" stroke="#666" strokeWidth="1.5"/>
          <polygon points="305,38 313,42 305,46" fill="#666"/>

          {/* output label */}
          <text x="315" y="38" fontSize="11" fontFamily="system-ui,sans-serif" fill="#444">dec_out</text>
          <text x="315" y="52" fontSize="9" fontFamily="system-ui,sans-serif" fill="#999" fontStyle="italic">→ He2 Merge</text>
        </svg>
      </div>

      <h3>Merge block — He2 pre-activation (He et al., ECCV 2016)</h3>
      <p>
        The skip-connection tensor and the upsampled decoder tensor are each
        projected through separate 3×3 convolutions, then <em>summed</em>
        (rather than concatenated). This is algebraically equivalent to
        concatenation+convolution but avoids materialising the doubled-channel
        tensor in memory. Two BN→ReLU→Conv refinement convolutions follow,
        with an identity shortcut over the merged sum:
      </p>
      <pre className="code-block">{`merged  = conv_skip(skip) + conv_dec(decoder_out)
conv1   = Conv( ReLU(BN(merged)) )
conv2   = Conv( ReLU(BN(conv1))  )
output  = conv2 + merged          # identity shortcut`}</pre>

      {/* ── He2 merge block diagram ── */}
      <div style={{ overflowX: "auto", margin: "0.75rem 0 1.25rem" }}>
        <svg viewBox="0 0 740 220" style={{ width: "100%", maxWidth: "740px", display: "block" }}
             aria-label="He2 merge block data-flow diagram">

          {/* ── skip input ── */}
          <text x="5" y="39" fontSize="12" fontFamily="system-ui,sans-serif" fill="#444" fontWeight="600">skip</text>
          <line x1="38" y1="35" x2="48" y2="35" stroke="#666" strokeWidth="1.5"/>
          <polygon points="48,31 56,35 48,39" fill="#666"/>
          <rect x="56" y="17" width="85" height="36" rx="4" fill="#e8e0f8" stroke="#6655bb" strokeWidth="1.3"/>
          <text x="98" y="31" textAnchor="middle" fontSize="10" fontFamily="system-ui,sans-serif" fill="#2a2070" fontWeight="600">conv_skip</text>
          <text x="98" y="45" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#6655bb">3×3</text>

          {/* ── dec input ── */}
          <text x="5" y="176" fontSize="12" fontFamily="system-ui,sans-serif" fill="#444" fontWeight="600">dec</text>
          <line x1="38" y1="172" x2="48" y2="172" stroke="#666" strokeWidth="1.5"/>
          <polygon points="48,168 56,172 48,176" fill="#666"/>
          <rect x="56" y="154" width="85" height="36" rx="4" fill="#e8e0f8" stroke="#6655bb" strokeWidth="1.3"/>
          <text x="98" y="168" textAnchor="middle" fontSize="10" fontFamily="system-ui,sans-serif" fill="#2a2070" fontWeight="600">conv_dec</text>
          <text x="98" y="182" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#6655bb">3×3</text>

          {/* ── routing: skip → top of ⊕₁ ── */}
          <line x1="141" y1="35" x2="215" y2="35" stroke="#666" strokeWidth="1.5"/>
          <line x1="215" y1="35" x2="215" y2="79" stroke="#666" strokeWidth="1.5"/>
          <polygon points="211,79 219,79 215,87" fill="#666"/>

          {/* ── routing: dec → bottom of ⊕₁ ── */}
          <line x1="141" y1="172" x2="215" y2="172" stroke="#666" strokeWidth="1.5"/>
          <line x1="215" y1="172" x2="215" y2="121" stroke="#666" strokeWidth="1.5"/>
          <polygon points="211,121 219,121 215,113" fill="#666"/>

          {/* ── ⊕₁ ── */}
          <circle cx="215" cy="100" r="13" fill="#fffacc" stroke="#aa8800" strokeWidth="1.5"/>
          <text x="215" y="105" textAnchor="middle" fontSize="15" fontFamily="system-ui,sans-serif" fill="#5a4000">⊕</text>
          <text x="215" y="127" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#999" fontStyle="italic">merged</text>

          {/* ── ⊕₁ → processing chain ── */}
          <line x1="228" y1="100" x2="238" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="238,96 246,100 238,104" fill="#666"/>

          {/* BN */}
          <rect x="246" y="82" width="36" height="36" rx="4" fill="#d8edd8" stroke="#3a7a3a" strokeWidth="1.3"/>
          <text x="264" y="105" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#1a4a1a" fontWeight="600">BN</text>
          <line x1="282" y1="100" x2="292" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="292,96 300,100 292,104" fill="#666"/>

          {/* ReLU */}
          <rect x="300" y="82" width="48" height="36" rx="4" fill="#fde8cc" stroke="#cc7a00" strokeWidth="1.3"/>
          <text x="324" y="105" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#7a3a00" fontWeight="600">ReLU</text>
          <line x1="348" y1="100" x2="358" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="358,96 366,100 358,104" fill="#666"/>

          {/* Conv 3×3 */}
          <rect x="366" y="82" width="68" height="36" rx="4" fill="#dce8f8" stroke="#4a7cc7" strokeWidth="1.3"/>
          <text x="400" y="97" textAnchor="middle" fontSize="10" fontFamily="system-ui,sans-serif" fill="#1a3a6b" fontWeight="600">Conv 3×3</text>
          <text x="400" y="111" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#4a7cc7">stride 1</text>
          <line x1="434" y1="100" x2="444" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="444,96 452,100 444,104" fill="#666"/>

          {/* BN */}
          <rect x="452" y="82" width="36" height="36" rx="4" fill="#d8edd8" stroke="#3a7a3a" strokeWidth="1.3"/>
          <text x="470" y="105" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#1a4a1a" fontWeight="600">BN</text>
          <line x1="488" y1="100" x2="498" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="498,96 506,100 498,104" fill="#666"/>

          {/* ReLU */}
          <rect x="506" y="82" width="48" height="36" rx="4" fill="#fde8cc" stroke="#cc7a00" strokeWidth="1.3"/>
          <text x="530" y="105" textAnchor="middle" fontSize="12" fontFamily="system-ui,sans-serif" fill="#7a3a00" fontWeight="600">ReLU</text>
          <line x1="554" y1="100" x2="564" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="564,96 572,100 564,104" fill="#666"/>

          {/* Conv 3×3 */}
          <rect x="572" y="82" width="68" height="36" rx="4" fill="#dce8f8" stroke="#4a7cc7" strokeWidth="1.3"/>
          <text x="606" y="97" textAnchor="middle" fontSize="10" fontFamily="system-ui,sans-serif" fill="#1a3a6b" fontWeight="600">Conv 3×3</text>
          <text x="606" y="111" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif" fill="#4a7cc7">stride 1</text>
          <line x1="640" y1="100" x2="650" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="650,96 658,100 650,104" fill="#666"/>

          {/* ⊕₂ */}
          <circle cx="671" cy="100" r="13" fill="#fffacc" stroke="#aa8800" strokeWidth="1.5"/>
          <text x="671" y="105" textAnchor="middle" fontSize="15" fontFamily="system-ui,sans-serif" fill="#5a4000">⊕</text>
          <line x1="684" y1="100" x2="696" y2="100" stroke="#666" strokeWidth="1.5"/>
          <polygon points="696,96 704,100 696,104" fill="#666"/>

          {/* output */}
          <text x="706" y="105" fontSize="13" fontFamily="system-ui,sans-serif" fill="#444">out</text>

          {/* ── identity shortcut arc (merged → ⊕₂) ── */}
          <path d="M 215,113 C 215,202 671,202 671,121"
                fill="none" stroke="#999" strokeWidth="1.3" strokeDasharray="5,3"/>
          <polygon points="667,121 675,121 671,113" fill="#999"/>
          <text x="443" y="212" textAnchor="middle" fontSize="9" fontFamily="system-ui,sans-serif"
                fill="#999" fontStyle="italic">identity shortcut (merged)</text>
        </svg>
      </div>

      <h3>Architecture sweep (conducted)</h3>
      <p>
        A 3×3 grid (classical · He2 · SE encoder × classical · He2 · attention-gate merge)
        was swept over 200 epochs, 2×T4 DDP, Adam lr=3×10⁻⁴, full augmentation.
        Rankings use the tail-mean of val Dice over the last 50 epochs:
        classical/He2 0.8409 (rank 1), classical/attention-gate 0.8351 (rank 2), SE/classical
        ~0.835 (rank 3). The 0.006-Dice margin triggered a 5-seed tie-break; the
        paired t-test (p=0.18, mean diff +0.0016) was non-significant, so the full-grid rank-1
        result was adopted by the conservative selection rule.
        The encoder choice drove more variance (marginal spread 0.006) than the merge block (0.003).
        The winning combination is <strong>classical encoder + He2 merge</strong>.
      </p>
    </section>

    {/* ── Training setup ─────────────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Training setup</h2>
      <table className="info-table">
        <tbody>
          <tr><td>Dataset</td>
              <td>ISIC 2017 — 2 000 train / 150 val / 600 test dermoscopic images</td></tr>
          <tr><td>Input resolution</td>
              <td>256 × 256 px, resized offline; normalised with dataset-computed mean &amp; std</td></tr>
          <tr><td>Batch size</td>
              <td>
                8 per GPU × 2 GPUs = 16 effective (DDP, ddp_spawn)<br />
                <span className="design-note">
                  Throughput sweep (bs 2→64, 2×T4): bs=8 is the smallest batch on the plateau
                  (≥81% of peak throughput in both augmented and non-augmented conditions) and the
                  last point before the time-per-step inflection. Augmentations add negligible cost
                  at this size. Peak GPU memory: 0.43 GB/GPU.
                </span>
              </td></tr>
          <tr><td>Max epochs</td>
              <td>300 with early stopping (patience 50, Δ min 0.002 on val Dice)</td></tr>
          <tr><td>Loss</td>
              <td>BCE-Dice: 0.5 × BCEWithLogitsLoss + 0.5 × Dice loss</td></tr>
          <tr><td>Optimiser</td>
              <td>Adam (β₁=0.9, β₂=0.999, ε=1e-8, weight decay=0)</td></tr>
          <tr><td>Learning rate</td>
              <td>
                3×10⁻⁴<br />
                <span className="design-note">
                  5-point log-spaced sweep [1e-4 … 3e-3], AdamW, 2×T4, 100 epochs.
                  lr=3×10⁻⁴ achieved the highest mean val Dice (0.806), lowest epoch variance
                  (σ=0.018), and cleanest convergence. Consistent with two prior Adam sweeps.
                  lr=3×10⁻³ caused clear degradation (mean Dice −0.018, convergence to 0.80
                  delayed by 35 epochs).
                </span>
              </td></tr>
          <tr><td>LR schedule</td>
              <td>
                Cosine annealing (T_max=300, η_min=1×10⁻⁶)<br />
                <span className="design-note">
                  Scheduler sweep (cosine annealing vs ReduceLROnPlateau, single seed): cosine
                  annealing 0.8635 val Dice at epoch 142; ReduceLROnPlateau 0.8625 at epoch 102.
                  Margin 0.001 is below the 0.01 practical-significance threshold.
                  Flat-LR baseline pending re-run; sweep ongoing.
                </span>
              </td></tr>
          <tr><td>Precision</td>
              <td>16-bit mixed (AMP, auto-set from accelerator)</td></tr>
          <tr><td>Hardware</td>
              <td>2 × NVIDIA T4 (Kaggle), PyTorch Lightning</td></tr>
          <tr><td>Weight init</td>
              <td>Kaiming normal (fan_in, ReLU) for all Conv2d/ConvTranspose2d; BN weights ~ N(1, 0.01)</td></tr>
          <tr><td>Checkpoint</td>
              <td>Best val Dice saved; optimal sigmoid threshold stored in checkpoint buffer</td></tr>
        </tbody>
      </table>
    </section>

    {/* ── Augmentation ───────────────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Augmentation pipeline (training only)</h2>
      <table className="info-table">
        <tbody>
          <tr><td>Spatial</td>
              <td>Square symmetry (D₄ group flips/rotations), affine (scale · translate · rotate ±20°), perspective, elastic deformation</td></tr>
          <tr><td>Photometric</td>
              <td>Colour jitter (brightness, contrast, saturation, hue), Gaussian blur, Gaussian noise</td></tr>
          <tr><td>Normalisation</td>
              <td>Per-channel standardisation with dataset statistics: μ = [0.699, 0.556, 0.512], σ = [0.158, 0.156, 0.171]</td></tr>
        </tbody>
      </table>
    </section>

    {/* ── Inference ──────────────────────────────────────────────────── */}
    <section className="doc-section">
      <h2>Inference pipeline</h2>
      <ol className="doc-list">
        <li>Image resized to 256 × 256 and normalised with the training-set statistics above.</li>
        <li>Forward pass through U-Net; raw logits passed through sigmoid → probabilities ∈ [0, 1].</li>
        <li>
          Threshold applied to produce the binary mask. The threshold is <em>not</em> fixed
          at 0.5 — at each validation epoch a vectorised sweep over 51 candidate thresholds
          (linspace 0→1) finds the value that maximises Dice on the full validation set.
          The best threshold is stored in the checkpoint and used at test / inference time.
        </li>
        <li>Mask returned to the caller at 256 × 256; the web app overlays it on the original image.</li>
      </ol>
    </section>

  </div>
);

export default NetworkDesignPage;
