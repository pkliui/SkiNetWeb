import express, { type Request, type Response } from "express";
import cors from "cors";
import multer from "multer";
import fs from "fs";
import path from "path";
import os from "os";
import { execSync } from "child_process";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT          = process.env["PORT"]          || 5000;
const INFERENCE_URL = process.env["INFERENCE_URL"] || "http://skinet-service:5001";
const KAGGLE_KERNEL = "kliuiev/isic-2017-256x256";

const CACHE_DIR      = path.join(os.tmpdir(), "isic-cache");
const IMAGES_DIR     = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Data", "ISIC-2017_Test_v2_Data");
const MASKS_DIR      = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Part1_GroundTruth", "ISIC-2017_Test_v2_Part1_GroundTruth");
const MANIFEST_PATH  = path.join(__dirname, "../../isic-manifest.json");

fs.mkdirSync(CACHE_DIR, { recursive: true });

const MANIFEST: string[] = (() => {
  try { return JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8")); }
  catch { console.warn("isic-manifest.json not found — gallery will be empty"); return []; }
})();

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
  const missing = ids.filter(id => !fs.existsSync(path.join(IMAGES_DIR, `${id}.jpg`)));
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

app.listen(PORT, () => console.log(`Backend running on port ${PORT}`));
