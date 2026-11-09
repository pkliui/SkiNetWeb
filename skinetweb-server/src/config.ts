import fs from "fs";
import path from "path";
import { cleanEnv, makeValidator, port, str } from "envalid";

const positiveInt = makeValidator<number>((input) => {
  const parsed = Number(input);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`must be a positive integer, got ${JSON.stringify(input)}`);
  }
  return parsed;
});

const env = cleanEnv(process.env, {
  PORT: port({ default: 5000 }),
  INFERENCE_URL: str({ default: "http://skinet-service:5001" }),
  SEGMENT_TIMEOUT_MS: positiveInt({ default: 5_000 }), // real ISIC image, 5 runs, max 1.65s
  CASE_REPORT_TIMEOUT_MS: positiveInt({ default: 50_000 }),
  STATUS_CHECK_TIMEOUT_MS: positiveInt({ default: 12_000 }),
  MAX_SEGMENT_CONCURRENCY: positiveInt({ default: 1 }), // was 2 — t3.small has no memory headroom for concurrent inference
  // No default: shared with the Python skinet-service's httpx connection pool
  // sizing (see main.py). A code default here would be a second place this
  // number lives and could silently drift from the Python side, so an
  // unset/invalid var is a hard startup error instead.
  MAX_CASE_REPORT_CONCURRENCY: positiveInt(),
  // No default: shared with the Python skinet-service's settings.py, which
  // enforces the same real limit rather than nginx's looser outer bound. Same
  // drift risk as MAX_CASE_REPORT_CONCURRENCY above.
  MAX_UPLOAD_BYTES: positiveInt(),
  ISIC_CACHE_DIR: str({ default: "/isic-cache" }),
});

export const PORT = env.PORT;
export const INFERENCE_URL = env.INFERENCE_URL;
// Coupled to a specific Kaggle dataset's folder layout (see ISIC_IMAGES_PATH/
// ISIC_MASKS_PATH below) — swapping datasets means updating the download/caching
// logic too, not just this string, so it's a source change, not an env var.
export const KAGGLE_DATASET = "kliuiev/isic-2017-test-256x256";

export const SEGMENT_TIMEOUT_MS = env.SEGMENT_TIMEOUT_MS;
// Must stay ABOVE the Python service's DEFAULT_TOTAL_BUDGET_SECONDS (40s), and below
// nginx's proxy_read_timeout (70s). The Python service degrades to a deterministic
// report when its own budget runs out; aborting before it can do so replaces a
// usable report with a bare 504, so this deadline only fires if that layer hangs.
// Measured: a successful call on a free-tier model took ~23s, so 30s was too tight.
export const CASE_REPORT_TIMEOUT_MS = env.CASE_REPORT_TIMEOUT_MS;

// skinet-service's status check runs up to two sequential HTTP calls (API-key
// check, then model list), each under its own ~5s budget (see
// DEFAULT_STATUS_CHECK_TIMEOUT_SECONDS in reporting/status.py) — 12s covers
// that worst case with headroom.
export const STATUS_CHECK_TIMEOUT_MS = env.STATUS_CHECK_TIMEOUT_MS;

// Must match nginx/default.conf's `proxy_read_timeout` for the /api location.
// That file is static (no envsubst — see nginx/Dockerfile), so it can't be read
// here; keep this constant in sync with it by hand.
const NGINX_PROXY_READ_TIMEOUT_MS = 70_000;
if (CASE_REPORT_TIMEOUT_MS >= NGINX_PROXY_READ_TIMEOUT_MS) {
  throw new Error(
    `CASE_REPORT_TIMEOUT_MS (${CASE_REPORT_TIMEOUT_MS}ms) must stay below nginx's proxy_read_timeout ` +
      `(${NGINX_PROXY_READ_TIMEOUT_MS}ms, see nginx/default.conf) or /case-report requests get cut off ` +
      `by nginx before Express's own timeout/degradation logic runs.`
  );
}

export const MAX_SEGMENT_CONCURRENCY = env.MAX_SEGMENT_CONCURRENCY;
// Shared with the Python skinet-service's httpx connection pool sizing (main.py);
// see the "No default" comment on this var above — both must enforce the same limit.
export const MAX_CASE_REPORT_CONCURRENCY = env.MAX_CASE_REPORT_CONCURRENCY;
export const MAX_UPLOAD_BYTES = env.MAX_UPLOAD_BYTES;

// Declared MIME types accepted for upload. Must match the PIL formats in
// ALLOWED_IMAGE_FORMATS in skinet-service/main.py, which checks the actual
// bytes, so this list is only the cheap early rejection.
export const ALLOWED_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set(["image/jpeg", "image/png"]);

// Persistent cache dir. Mount a named Docker volume here so the download
// survives container restarts. Falls back to /tmp in local dev.
export const CACHE_DIR = env.ISIC_CACHE_DIR;

// Paths produced by `kaggle datasets download kliuiev/isic-2017-test-256x256 --unzip`.
export const ISIC_IMAGES_PATH = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Data");
export const ISIC_MASKS_PATH = path.join(CACHE_DIR, "ISIC-2017_Test_v2_Part1_GroundTruth");
export const CACHE_SENTINEL = path.join(CACHE_DIR, ".cache-ready");

fs.mkdirSync(CACHE_DIR, { recursive: true });
