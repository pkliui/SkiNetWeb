import express, { type Request, type Response } from "express";
import cors from "cors";
import multer from "multer";
import fs from "fs";
import path from "path";
import { exec } from "child_process";

const PORT           = process.env["PORT"]           || 5000;
const INFERENCE_URL  = process.env["INFERENCE_URL"]  || "http://skinet-service:5001";
const KAGGLE_DATASET = "kliuiev/isic-2017-test-256x256";

// Persistent cache dir — mount a named Docker volume here so the download
// survives container restarts. Falls back to /tmp in local dev.
const CACHE_DIR = process.env["ISIC_CACHE_DIR"] || "/isic-cache";

// Paths produced by `kaggle datasets download kliuiev/isic-2017-test-256x256 --unzip`
const ISIC_IMAGES_PATH = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Data");
const ISIC_MASKS_PATH  = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Part1_GroundTruth");
const CACHE_SENTINEL   = path.join(CACHE_DIR, ".cache-ready");

fs.mkdirSync(CACHE_DIR, { recursive: true });

const app = express();
app.use(cors());

const upload = multer({ storage: multer.memoryStorage() });

// ── Inference ────────────────────────────────────────────────────────────────

app.post("/api/segment", upload.single("image"), async (req: Request, res: Response) => {
  if (!req.file) { res.status(400).json({ error: "No image file provided" }); return; }
  try {
    const formData = new FormData();
    const blob = new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype });
    formData.append("image", blob, req.file.originalname);
    const inferenceRes = await fetch(`${INFERENCE_URL}/infer`, { method: "POST", body: formData });
    if (!inferenceRes.ok) { res.status(502).json({ error: "Inference service error" }); return; }
    res.set("Content-Type", "image/png");
    res.send(Buffer.from(await inferenceRes.arrayBuffer()));
  } catch {
    res.status(503).json({ error: "Inference service unavailable" });
  }
});

// ── Kaggle download ───────────────────────────────────────────────────────────

/** Download files whose ISIC IDs are not yet in the cache. */
function ensureCached(ids: string[]): void {
  const missing = ids.filter(id =>
    !fs.existsSync(path.join(IMAGES_DIR, `${id}.jpg`)) ||
    !fs.existsSync(path.join(MASKS_DIR,  `${id}_segmentation.png`))
  );
  if (missing.length === 0) return;

  // One Kaggle CLI call fetches all missing images + their masks in one shot.
  const pattern = missing.map(id => id.replace("ISIC_", "ISIC\\_")).join("|");
  execSync(
    `kaggle kernels output ${KAGGLE_KERNEL} --file-pattern "${pattern}" -p ${CACHE_DIR} -q --force`,
    { stdio: "inherit", timeout: 120_000 }
  );
}

function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j]!, copy[i]!];
  }
  return copy.slice(0, n);
}

// ── Random examples ───────────────────────────────────────────────────────────

app.get("/api/random-examples", (req: Request, res: Response) => {
  if (MANIFEST.length === 0) { res.status(503).json({ error: "Manifest not loaded" }); return; }

  const raw   = req.query["count"];
  const count = Math.min(Math.max(parseInt(typeof raw === "string" ? raw : "5") || 5, 1), 20);

  // Pick random filenames (e.g. "ISIC_0012086.jpg") and extract IDs.
  const picks = pickRandom<string>(MANIFEST, count);
  const ids   = picks.map(f => path.parse(f).name);   // "ISIC_0012086"

  try {
    ensureCached(ids);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("Kaggle download failed:", msg);
    res.status(502).json({ error: "Failed to fetch examples from Kaggle" });
    return;
  }

  const results = ids.map(id => {
    const maskFile = `${id}_segmentation.png`;
    const hasMask  = fs.existsSync(path.join(MASKS_DIR, maskFile));
    return {
      imageSrc: `/api/isic-image/${encodeURIComponent(`${id}.jpg`)}`,
      gtSrc:    hasMask ? `/api/isic-mask/${encodeURIComponent(maskFile)}` : null,
      label:    id,
    };
  });

  res.json(results);
});

// ── File serving ──────────────────────────────────────────────────────────────

app.get("/api/isic-image/:filename", (req: Request, res: Response) => {
  const raw      = req.params["filename"];
  const filename = decodeURIComponent(typeof raw === "string" ? raw : (raw?.[0] ?? ""));
  if (!filename) { res.status(400).send(); return; }
  const filePath = path.resolve(IMAGES_DIR, filename);
  if (!filePath.startsWith(path.resolve(IMAGES_DIR) + path.sep)) { res.status(403).send(); return; }
  if (!fs.existsSync(filePath)) { res.status(404).send(); return; }
  res.sendFile(filePath);
});

app.get("/api/isic-mask/:filename", (req: Request, res: Response) => {
  const raw      = req.params["filename"];
  const filename = decodeURIComponent(typeof raw === "string" ? raw : (raw?.[0] ?? ""));
  if (!filename) { res.status(400).send(); return; }
  const filePath = path.resolve(MASKS_DIR, filename);
  if (!filePath.startsWith(path.resolve(MASKS_DIR) + path.sep)) { res.status(403).send(); return; }
  if (!fs.existsSync(filePath)) { res.status(404).send(); return; }
  res.sendFile(filePath);
});

// Downloads the full Kaggle dataset once at startup and unzips it in place.
// Uses a sentinel file so subsequent restarts skip the download.
// Kaggle credentials must be supplied via KAGGLE_USERNAME + KAGGLE_KEY env vars.
let cacheInitStarted = false;

function initCacheInBackground(): void {
  if (cacheInitStarted || fs.existsSync(CACHE_SENTINEL)) return;
  cacheInitStarted = true;
  console.log("Downloading ISIC dataset from Kaggle (one-time)…");
  exec(
    `kaggle datasets download -d ${KAGGLE_DATASET} -p ${CACHE_DIR} --unzip`,
    { timeout: 600_000 },
    (err: Error | null) => {
      if (err) {
        console.error("Kaggle download failed:", err.message);
        cacheInitStarted = false;
        return;
      }
      fs.writeFileSync(CACHE_SENTINEL, new Date().toISOString());
      console.log("ISIC cache ready — images and GT masks available.");
    }
  );
}

app.listen(PORT, () => {
  console.log(`Backend is running on port ${PORT}`);
  initCacheInBackground();
});
