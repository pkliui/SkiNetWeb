import express, { type Request, type Response } from "express";
import cors from "cors";
import multer from "multer";
import fs from "fs";
import path from "path";
import os from "os";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT          = process.env["PORT"]          || 5000;
const INFERENCE_URL = process.env["INFERENCE_URL"] || "http://skinet-service:5001";
const KAGGLE_USER   = process.env["KAGGLE_USERNAME"] || "";
const KAGGLE_KEY    = process.env["KAGGLE_KEY"]      || "";

const KAGGLE_KERNEL  = "kliuiev/isic-2017-256x256";
const IMG_PREFIX     = "ISIC-2017_Test_v2_Data/ISIC-2017_Test_v2_Data";
const MASK_PREFIX    = "ISIC-2017_Test_v2_Part1_GroundTruth/ISIC-2017_Test_v2_Part1_GroundTruth";
const CACHE_DIR      = path.join(os.tmpdir(), "isic-cache");
const MANIFEST_PATH  = path.join(__dirname, "../../isic-manifest.json");

fs.mkdirSync(CACHE_DIR, { recursive: true });

const MANIFEST: string[] = (() => {
  try { return JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8")); }
  catch { console.warn("isic-examples/manifest.json not found — gallery will be empty"); return []; }
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

// ── Kaggle helpers ────────────────────────────────────────────────────────────

function kaggleAuth(): string {
  if (!KAGGLE_USER || !KAGGLE_KEY) throw new Error("KAGGLE_USERNAME / KAGGLE_KEY not set");
  return "Basic " + Buffer.from(`${KAGGLE_USER}:${KAGGLE_KEY}`).toString("base64");
}

async function fetchKaggleFile(kernelPath: string): Promise<Buffer> {
  const url = `https://www.kaggle.com/api/v1/kernels/output/${KAGGLE_KERNEL}?fileName=${encodeURIComponent(kernelPath)}`;
  const res = await fetch(url, { headers: { Authorization: kaggleAuth() } });
  if (!res.ok) throw new Error(`Kaggle fetch failed ${res.status}: ${kernelPath}`);
  return Buffer.from(await res.arrayBuffer());
}

async function getCachedFile(cacheKey: string, kernelPath: string): Promise<string> {
  const dest = path.join(CACHE_DIR, cacheKey);
  if (!fs.existsSync(dest)) {
    const buf = await fetchKaggleFile(kernelPath);
    fs.writeFileSync(dest, buf);
  }
  return dest;
}

/** Fisher-Yates pick n from array */
function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j]!, copy[i]!];
  }
  return copy.slice(0, n);
}

// ── Random examples ───────────────────────────────────────────────────────────

app.get("/api/random-examples", async (req: Request, res: Response) => {
  if (MANIFEST.length === 0) { res.status(503).json({ error: "Manifest not loaded" }); return; }
  if (!KAGGLE_USER || !KAGGLE_KEY) { res.status(503).json({ error: "Kaggle credentials not configured" }); return; }

  const raw   = req.query["count"];
  const count = Math.min(Math.max(parseInt(typeof raw === "string" ? raw : "5") || 5, 1), 20);
  const picks = pickRandom(MANIFEST, count);

  try {
    const results = await Promise.all(picks.map(async (imgFile) => {
      const base    = path.parse(imgFile).name;
      const maskFile = `${base}_segmentation.png`;
      // pre-fetch both image and mask in parallel; mask 404 is non-fatal
      const [, maskOk] = await Promise.allSettled([
        getCachedFile(imgFile,  `${IMG_PREFIX}/${imgFile}`),
        getCachedFile(maskFile, `${MASK_PREFIX}/${maskFile}`),
      ]);
      return {
        imageSrc: `/api/isic-image/${encodeURIComponent(imgFile)}`,
        gtSrc:    maskOk.status === "fulfilled" ? `/api/isic-mask/${encodeURIComponent(maskFile)}` : null,
        label:    base,
      };
    }));
    res.json(results);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(502).json({ error: msg });
  }
});

// ── File serving ──────────────────────────────────────────────────────────────

function serveCache(filename: string, res: Response): void {
  const safe = path.basename(filename);
  const dest  = path.join(CACHE_DIR, safe);
  if (!fs.existsSync(dest)) { res.status(404).send(); return; }
  res.sendFile(dest);
}

app.get("/api/isic-image/:filename", (req: Request, res: Response) => {
  const f = req.params["filename"];
  if (!f) { res.status(400).send(); return; }
  serveCache(decodeURIComponent(typeof f === "string" ? f : f[0] ?? ""), res);
});

app.get("/api/isic-mask/:filename", (req: Request, res: Response) => {
  const f = req.params["filename"];
  if (!f) { res.status(400).send(); return; }
  serveCache(decodeURIComponent(typeof f === "string" ? f : f[0] ?? ""), res);
});

app.listen(PORT, () => console.log(`Backend running on port ${PORT}`));
