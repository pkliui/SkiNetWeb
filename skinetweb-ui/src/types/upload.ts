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
