import { exec } from "child_process";
import fs from "fs";
import path from "path";

import { CACHE_DIR, CACHE_SENTINEL, KAGGLE_DATASET } from "../config.js";

// Downloads the full Kaggle dataset once at startup and unzips it in place.
// Uses a sentinel file so subsequent restarts skip the download.
// Kaggle credentials must be supplied via KAGGLE_USERNAME + KAGGLE_KEY env vars.
let cacheInitStarted = false;
const CACHE_LOCK_DIR = path.join(CACHE_DIR, ".cache-download.lock");

export function isCacheReady(): boolean {
  return fs.existsSync(CACHE_SENTINEL);
}

export function initCacheInBackground(): void {
  if (cacheInitStarted || isCacheReady()) return;

  // Fail loud, not silent: without credentials the Kaggle CLI errors out and the
  // gallery would just return 503 with no hint why. Surface the real cause.
  if (!process.env["KAGGLE_USERNAME"] || !process.env["KAGGLE_KEY"]) {
    console.error(
      "KAGGLE_USERNAME / KAGGLE_KEY not set - skipping ISIC download. " +
        "The examples gallery will be empty (503). Add them to the .env next to " +
        "docker-compose so Compose passes them into this container.",
    );
    return;
  }

  try {
    fs.mkdirSync(CACHE_LOCK_DIR);
  } catch (error) {
    if (isCacheReady()) return;
    if (error instanceof Error && "code" in error && error.code === "EEXIST") {
      console.log("ISIC cache download already in progress in another server process.");
      return;
    }

    console.error("Unable to acquire ISIC cache download lock:", error);
    return;
  }

  cacheInitStarted = true;
  console.log("Downloading ISIC dataset from Kaggle (one-time)...");
  exec(
    `kaggle datasets download -d ${KAGGLE_DATASET} -p ${CACHE_DIR} --unzip`,
    { timeout: 600_000 },
    (err: Error | null) => {
      if (err) {
        console.error("Kaggle download failed:", err.message);
        cacheInitStarted = false;
        fs.rmSync(CACHE_LOCK_DIR, { force: true, recursive: true });
        return;
      }

      fs.writeFileSync(CACHE_SENTINEL, new Date().toISOString());
      fs.rmSync(CACHE_LOCK_DIR, { force: true, recursive: true });
      console.log("ISIC cache ready - images and GT masks available.");
    },
  );
}
