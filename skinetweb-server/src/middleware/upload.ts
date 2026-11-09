import type { NextFunction, Request, RequestHandler, Response } from "express";
import multer from "multer";

import { ALLOWED_IMAGE_MIME_TYPES, MAX_UPLOAD_BYTES } from "../config.js";

/**
 * Error thrown when an uploaded file is not a supported image type.
 *
 * Supported image formats are:
 * - JPEG (`image/jpeg`)
 * - PNG (`image/png`)
 */
class UnsupportedImageTypeError extends Error {}

// MAX_UPLOAD_BYTES is a whole number of MiB (10 MiB in .env.config); round to one
// decimal so the message stays readable if it ever isn't.
const MAX_UPLOAD_MB = Math.round((MAX_UPLOAD_BYTES / (1024 * 1024)) * 10) / 10;

/**
 * Multer configuration for handling image uploads.
 *
 * This uploader is configured for the segmentation endpoint, where uploaded
 * images are not persisted locally. Files are stored in memory because they are
 * only required temporarily before being forwarded to the inference service.
 *
 * Upload lifecycle:
 *
 * 1. A client sends a multipart/form-data request containing a file under the
 *    "image" field.
 * 2. `imageUpload.single("image")` activates Multer processing for the request.
 * 3. Multer extracts the uploaded file metadata and invokes `fileFilter`.
 * 4. The filter validates the MIME type before allowing the upload to proceed.
 * 5. Accepted files are stored in memory and exposed through `req.file`.
 *
 * Security and resource constraints:
 * - Only one file is accepted per request.
 * - Maximum upload size is limited by MAX_UPLOAD_BYTES to prevent excessive
 *   memory consumption.
 * - Only JPEG and PNG images are accepted.
 *
 * Rejected uploads are propagated as errors and converted into API responses
 * by `parseImageUpload`.
 */
const imageUpload = multer({
    storage: multer.memoryStorage(),
    limits: {
      fileSize: MAX_UPLOAD_BYTES,
      files: 1,
    },
    fileFilter: (_req, file, cb) => {
      if (ALLOWED_IMAGE_MIME_TYPES.has(file.mimetype)) {
        cb(null, true);
        return;
      }

      cb(new UnsupportedImageTypeError("Only JPEG and PNG images are supported"));
    },
  });

/**
 * Express middleware responsible for parsing and validating incoming image
 * uploads.
 *
 * This middleware wraps Multer's upload handler to provide application-specific
 * error handling and a stable API contract.
 *
 * Expected request format:
 * - Content-Type: multipart/form-data
 * - File field name: "image"
 * - Maximum files: 1
 * - Supported formats: JPEG, PNG
 *
 * On successful processing:
 * - Multer attaches the uploaded file to `req.file`.
 * - Execution continues to the next middleware/controller via `next()`.
 *
 * Error handling:
 * - 413 Payload Too Large:
 *   The uploaded image exceeds MAX_UPLOAD_BYTES.
 *
 * - 400 Bad Request:
 *   The uploaded file type is unsupported or the upload payload is invalid.
 *
 * The controller layer can assume that when this middleware completes
 * successfully, `req.file` contains a validated image ready for inference.
 */
export const parseImageUpload: RequestHandler = (
  req: Request,
  res: Response,
  next: NextFunction,
): void => {
  imageUpload.single("image")(req, res, (err: unknown) => {
    if (!err) {
      next();
      return;
    }

    if (err instanceof multer.MulterError && err.code === "LIMIT_FILE_SIZE") {
      res.status(413).json({ error: `Image is too large. Maximum size is ${MAX_UPLOAD_MB} MB.` });
      return;
    }

    if (err instanceof UnsupportedImageTypeError) {
      res.status(400).json({ error: err.message });
      return;
    }

    res.status(400).json({ error: "Invalid image upload" });
  });
};
