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

app.post("/api/segment", upload.single("image"), async (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ error: "No image file provided" });
    return;
  }

  try {
    const formData = new FormData();
    const blob = new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype });
    formData.append("image", blob, req.file.originalname);

    const inferenceRes = await fetch(`${INFERENCE_URL}/infer`, {
      method: "POST",
      body: formData,
    });

    if (!inferenceRes.ok) {
      res.status(502).json({ error: "Inference service error" });
      return;
    }

    const maskBuffer = Buffer.from(await inferenceRes.arrayBuffer());
    res.set("Content-Type", "image/png");
    res.send(maskBuffer);
  } catch {
    res.status(503).json({ error: "Inference service unavailable" });
  }
});

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg"]);

/** Fisher-Yates shuffle, returns up to n elements. */
function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j]!, copy[i]!];
  }
  return copy.slice(0, n);
}

/**
 * Returns N randomly chosen ISIC images from ISIC_IMAGES_PATH,
 * each paired with its GT mask from ISIC_MASKS_PATH when available.
 * Query param: count (default 5, max 20).
 */
app.get("/api/random-examples", (req: Request, res: Response) => {
  const raw   = req.query["count"];
  const count = Math.min(Math.max(parseInt(typeof raw === "string" ? raw : "5") || 5, 1), 20);

  if (!fs.existsSync(ISIC_IMAGES_PATH)) {
    res.status(503).json({ error: "ISIC images folder not mounted" });
    return;
  }

  const images = fs.readdirSync(ISIC_IMAGES_PATH).filter((f: string) => {
    const ext = path.extname(f).toLowerCase();
    return IMAGE_EXTS.has(ext) && !f.includes("_segmentation") && !f.includes("_lesion") && !f.includes("_superpixels");
  });

  if (images.length === 0) {
    res.status(404).json({ error: "No images found in ISIC images folder" });
    return;
  }

  const masksAvailable = fs.existsSync(ISIC_MASKS_PATH);

  const results = pickRandom(images, count).map((img: string) => {
    const base   = path.parse(img).name;
    const gtFile = masksAvailable
      ? [`${base}_segmentation.png`, `${base}_lesion.png`]
          .find((f: string) => fs.existsSync(path.join(ISIC_MASKS_PATH, f)))
      : undefined;
    return {
      imageSrc: `/api/isic-image/${encodeURIComponent(img)}`,
      gtSrc:    gtFile ? `/api/isic-mask/${encodeURIComponent(gtFile)}` : null,
      label:    base,
    };
  });

  res.json(results);
});

/** Serves an individual image file from ISIC_IMAGES_PATH. */
app.get("/api/isic-image/:filename", (req: Request, res: Response) => {
  const raw      = req.params["filename"];
  const filename = decodeURIComponent(typeof raw === "string" ? raw : (raw?.[0] ?? ""));
  if (!filename) { res.status(400).send(); return; }
  const filePath = path.resolve(ISIC_IMAGES_PATH, filename);
  if (!filePath.startsWith(path.resolve(ISIC_IMAGES_PATH) + path.sep)) {
    res.status(403).send(); return;
  }
  if (!fs.existsSync(filePath)) { res.status(404).send(); return; }
  res.sendFile(filePath);
});

/** Serves an individual mask file from ISIC_MASKS_PATH. */
app.get("/api/isic-mask/:filename", (req: Request, res: Response) => {
  const raw      = req.params["filename"];
  const filename = decodeURIComponent(typeof raw === "string" ? raw : (raw?.[0] ?? ""));
  if (!filename) { res.status(400).send(); return; }
  const filePath = path.resolve(ISIC_MASKS_PATH, filename);
  if (!filePath.startsWith(path.resolve(ISIC_MASKS_PATH) + path.sep)) {
    res.status(403).send(); return;
  }
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
