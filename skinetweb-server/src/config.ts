import fs from "fs";
import path from "path";

function numberFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;

  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const PORT = process.env["PORT"] || 5000;
export const INFERENCE_URL = process.env["INFERENCE_URL"] || "http://skinet-service:5001";
export const KAGGLE_DATASET = "kliuiev/isic-2017-test-256x256";

export const SEGMENT_TIMEOUT_MS = numberFromEnv("SEGMENT_TIMEOUT_MS", 5_000); // real ISIC image, 5 runs, max 1.65s
export const CASE_REPORT_TIMEOUT_MS = numberFromEnv("CASE_REPORT_TIMEOUT_MS", 30_000);  // TODO: likely too tight for LLM calls, pending real test
export const MAX_SEGMENT_CONCURRENCY = numberFromEnv("MAX_SEGMENT_CONCURRENCY", 1); // was 2 — t3.small has no memory headroom for concurrent inference
export const MAX_CASE_REPORT_CONCURRENCY = numberFromEnv("MAX_CASE_REPORT_CONCURRENCY", 5);
export const MAX_UPLOAD_BYTES = numberFromEnv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024);

// Persistent cache dir. Mount a named Docker volume here so the download
// survives container restarts. Falls back to /tmp in local dev.
export const CACHE_DIR = process.env["ISIC_CACHE_DIR"] || "/isic-cache";

// Paths produced by `kaggle datasets download kliuiev/isic-2017-test-256x256 --unzip`.
export const ISIC_IMAGES_PATH = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Data");
export const ISIC_MASKS_PATH = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Part1_GroundTruth");
export const CACHE_SENTINEL = path.join(CACHE_DIR, ".cache-ready");

fs.mkdirSync(CACHE_DIR, { recursive: true });
