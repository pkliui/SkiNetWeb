/**
 * HTTP API for browsing the locally cached ISIC dataset.
 *
 * This router exposes endpoints that allow the frontend to discover and
 * retrieve example images and their corresponding ground-truth segmentation
 * masks from the local ISIC dataset cache.
 *
 * Responsibilities:
 *
 * - Select random examples for demonstration purposes.
 * - Expose dataset images through HTTP endpoints.
 * - Expose corresponding ground-truth segmentation masks when available.
 * - Validate requested paths before serving files to prevent path traversal
 *   attacks.
 *
 */

import { Router, type NextFunction, type Request, type Response } from "express";
import { promises as fs } from "fs";
import path from "path";

import { ISIC_IMAGES_PATH, ISIC_MASKS_PATH } from "../config.js";
import { isCacheReady } from "../cache/isicCache.js";
import { sendServiceError } from "../utils/errors.js";
import { fileExists } from "../utils/files.js";

export const isicRouter = Router();

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg"]);

// Static dataset files never change once cached, so it's safe to let the
// browser (and any intermediate CDN/proxy) hold onto them for a while.
const DATASET_FILE_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 1 day

function getSendFileStatusCode(err: Error): number {
  return "statusCode" in err && typeof err.statusCode === "number" ? err.statusCode : 500;
}

/**
 * Selects up to `n` random elements from an array.
 *
 * A copy of the input array is shuffled using the Fisher-Yates algorithm so
 * that the original collection remains unchanged. Here it is the modified version
 * by Durstenfeld where we move the "struck" numbers to the end of the list by swapping
 * them with the last unstruck number at each iteration.
 *
 * @param arr
 * Source collection.
 *
 * @param n
 * Maximum number of elements to return.
 *
 * @returns
 * A randomly selected subset of the input array.
 */
function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j]!, copy[i]!];
  }
  return copy.slice(0, n);
}

/**
 * Returns metadata describing a random subset of cached ISIC examples.
 *
 * Each returned object contains URLs that the frontend can subsequently use
 * to download the source image and, when available, its corresponding
 * ground-truth segmentation mask.
 *
 * Query parameters:
 *
 * - count
 *     Number of examples to return.
 *     Defaults to 5 and is clamped to the range [1, 20].
 *
 * Response example:
 *
 * [
 *   {
 *     imageSrc: "/api/isic-image/ISIC_0001.jpg",
 *     gtSrc: "/api/isic-mask/ISIC_0001_segmentation.png",
 *     label: "ISIC_0001"
 *   }
 * ]
 *
 * Errors thrown while reading the cache (e.g. a permissions issue, or the
 * directory disappearing between the existence check and the read) are caught
 * and translated into a JSON HTTP response.
 */
isicRouter.get("/api/random-examples", async (req: Request, res: Response) => {
  try {
    const raw = req.query["count"];
    const count = Math.min(Math.max(parseInt(typeof raw === "string" ? raw : "5") || 5, 1), 20);

    if (!isCacheReady()) {
      res.status(503).json({ error: "ISIC cache initialising, please retry shortly" });
      return;
    }

    const images = (await fs.readdir(ISIC_IMAGES_PATH)).filter((f: string) => {
      const ext = path.extname(f).toLowerCase();
      return IMAGE_EXTS.has(ext) && !f.includes("_segmentation") && !f.includes("_lesion") && !f.includes("_superpixels");
    });

    if (images.length === 0) {
      res.status(404).json({ error: "No images found in ISIC cache" });
      return;
    }

    const selected = pickRandom(images, count);

    const results = await Promise.all(
      selected.map(async (img: string) => {
        const base = path.parse(img).name;
        const maskFile = `${base}_segmentation.png`;
        const hasMask = await fileExists(path.join(ISIC_MASKS_PATH, maskFile));

        return {
          imageSrc: `/api/isic-image/${encodeURIComponent(img)}`,
          gtSrc: hasMask ? `/api/isic-mask/${encodeURIComponent(maskFile)}` : null,
          label: base,
        };
      }),
    );
    res.json(results);
  } catch (error) {
    sendServiceError(res, error, {
      timedOut: "Timed out reading the ISIC cache",
      unavailable: "ISIC cache is currently unavailable",
    });
  }
});

/**
 * Serves a dataset file from a configured root directory.
 *
 * The helper centralises the common logic used by dataset file endpoints,
 * including request validation, secure file serving and HTTP error handling.
 *
 * Before attempting to serve a file, the requested filename is validated to
 * ensure that a value was supplied. Files are then served using Express'
 * `sendFile()` API with the `root` option, allowing Express to safely resolve
 * the requested path relative to the configured dataset directory. This
 * prevents clients from accessing files outside the permitted root through
 * path traversal attacks (e.g. `../../etc/passwd`).
 *
 * Any errors reported by `sendFile()` are translated into appropriate HTTP
 * responses. Express determines whether the failure corresponds to a missing
 * file, an invalid path, or another filesystem error.
 *
 * @param root
 * Root directory containing the dataset files to expose.
 *
 * @param filename
 * Requested filename, resolved relative to `root`.
 *
 * @param res
 * Express response used to stream the requested file or return an error.
 *
 * @param next
 * Express continuation used if a streaming error happens after headers have
 * already been sent.
 */
function sendDatasetFile(root: string, filename: string, res: Response, next: NextFunction): void {
  if (!isCacheReady()) {
    res.status(503).json({ error: "ISIC cache initialising, please retry shortly" });
    return;
  }

  if (!filename) {
    res.status(400).json({ error: "Dataset filename is required" });
    return;
  }

  res.sendFile(filename, { root, maxAge: DATASET_FILE_MAX_AGE_MS }, (err) => {
    if (!err) {
      return;
    }

    if (res.headersSent) {
      next(err);
      return;
    }

    const statusCode = getSendFileStatusCode(err);
    if (statusCode === 404) {
      res.status(404).json({ error: "Dataset file not found" });
      return;
    }

    if (statusCode === 403) {
      res.status(403).json({ error: "Dataset file is not accessible" });
      return;
    }

    res.status(500).json({ error: "Unable to read dataset file" });
  });
}

/**
 * Serves an individual ISIC source image.
 *
 * The requested filename is validated before being resolved to a filesystem
 * path. Requests attempting to escape the configured dataset directory are
 * rejected to prevent path traversal attacks.
 *
 * Note: `req.params.filename` is already URL-decoded by Express, so no
 * additional `decodeURIComponent()` call is needed (or wanted) here — a
 * second decode pass is the classic way double-encoded traversal payloads
 * slip past naive string-based checks, and it can also throw on a filename
 * containing a literal `%`.
 *
 * This is triggered by the browser automatically when it renders
 * <img src="/api/isic-image/...">, and again manually by urlToFile() when the
 * user clicks a thumbnail in ExampleGallery.tsx.
 */
isicRouter.get("/api/isic-image/:filename", (req, res, next) => {
  const raw = req.params["filename"];
  const filename = typeof raw === "string" ? raw : (raw?.[0] ?? "");
  sendDatasetFile(ISIC_IMAGES_PATH, filename, res, next);
});

/**
 * Serves an individual ISIC source mask.
 *
 * The requested filename is validated before being resolved to a filesystem
 * path. Requests attempting to escape the configured dataset directory are
 * rejected to prevent path traversal attacks.
 *
 * Note: see the comment on the `/api/isic-image/:filename` handler above —
 * `req.params.filename` is already decoded by Express.
 *
 * This is triggered by the browser automatically when it renders
 * <img src="/api/isic-mask/...">, and again manually by urlToFile() when the
 * user clicks a thumbnail in ExampleGallery.tsx.
 */
isicRouter.get("/api/isic-mask/:filename", (req, res, next) => {
  const raw = req.params["filename"];
  const filename = typeof raw === "string" ? raw : (raw?.[0] ?? "");
  sendDatasetFile(ISIC_MASKS_PATH, filename, res, next);
});
