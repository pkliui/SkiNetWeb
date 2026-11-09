/**
 * Image types the upload accepts, by declared MIME type.
 *
 * Used for the file picker's `accept` filter and for the check in
 * `useSegmentation.onFileSelect`, which also covers drag-and-drop (the picker
 * filter does not). Both are convenience only: the browser derives `File.type`
 * from the file extension, so the server re-checks the declared type and then
 * the actual bytes.
 *
 * Must match ALLOWED_IMAGE_MIME_TYPES in skinetweb-server/src/config.ts.
 */
export const ALLOWED_IMAGE_MIME_TYPES: readonly string[] = ["image/jpeg", "image/png"];

/** Same wording as the server's rejection, so the user sees one message either way. */
export const UNSUPPORTED_IMAGE_TYPE_MESSAGE = "Only JPEG and PNG images are supported";

/**
 * Largest upload the server accepts, in bytes (10 MiB).
 *
 * Checked in `useSegmentation.onFileSelect` so an oversized file is rejected
 * before it is uploaded, instead of after a full upload just to get a 413.
 * Convenience only: Express and the inference service enforce the real limit.
 *
 * Must match MAX_UPLOAD_BYTES in .env.config. The UI build can't read that
 * file, so this is a hand-synced copy, like the message in nginx/default.conf.
 */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const MAX_UPLOAD_MB = Math.round((MAX_UPLOAD_BYTES / (1024 * 1024)) * 10) / 10;

/** Same wording as the server's 413, so the user sees one message either way. */
export const UPLOAD_TOO_LARGE_MESSAGE = `Image is too large. Maximum size is ${MAX_UPLOAD_MB} MB.`;
