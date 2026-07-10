/**
 * Service layer for communication with the external inference backend.
 *
 * This module encapsulates outbound HTTP communication with the ML inference
 * service and keeps transport details separate from Express route handlers.
 *
 * Responsibilities:
 *
 * - Build requests expected by the inference API.
 * - Apply configured request timeouts.
 * - Convert inference responses into application-level return values.
 * - Normalize upstream failures into application-specific errors.
 *
 * The router layer should delegate inference operations to this module instead
 * of constructing HTTP requests directly.
 */

import { CASE_REPORT_TIMEOUT_MS, INFERENCE_URL, SEGMENT_TIMEOUT_MS } from "../config.js";
import { UpstreamServiceError } from "../utils/errors.js";

/**
 * Sends an image to the inference backend for segmentation.
 *
 * The input file is expected to originate from Multer's multipart upload
 * middleware. The function converts the Node.js Buffer provided by Multer
 * into a Blob-based multipart request compatible with the Fetch API.
 *
 * Request flow:
 *
 *   Express request
 *        |
 *        v
 *   Multer file (Buffer)
 *        |
 *        v
 *   Multipart request to inference service
 *        |
 *        v
 *   Segmentation mask PNG response
 *
 * The inference service performs the actual ML inference. This function acts
 * as a client adapter between the API layer and the inference backend.
 *
 * @param file
 *   Uploaded image file provided by Multer.
 *
 * @returns
 *   PNG image bytes containing the generated segmentation mask.
 *
 * @throws UpstreamServiceError
 *   When the inference backend returns an unsuccessful HTTP response.
 *
 * @throws AbortError
 *   When the inference request exceeds the configured timeout.
 */
export async function segmentImage(file: Express.Multer.File): Promise<Buffer> {
  const formData = new FormData();

  // Multer exposes a Node Buffer; Node's fetch/FormData path expects a Blob
  // when we want to preserve filename and content type in the proxied upload.
  const blob = new Blob([new Uint8Array(file.buffer)], { type: file.mimetype });
  formData.append("image", blob, file.originalname);

  const inferenceRes = await fetch(`${INFERENCE_URL}/infer`, {
    method: "POST",
    body: formData,
    signal: AbortSignal.timeout(SEGMENT_TIMEOUT_MS),
  });

  if (!inferenceRes.ok) {
    throw new UpstreamServiceError(502, { error: "Inference service error" });
  }

  return Buffer.from(await inferenceRes.arrayBuffer());
}

/**
 * Requests a structured case report from the inference backend.
 *
 * This function forwards JSON input to the report-generation endpoint and
 * returns the structured response payload produced by the inference service.
 *
 * Request flow:
 *
 *   API request body
 *        |
 *        v
 *   JSON serialization
 *        |
 *        v
 *   Case report inference endpoint
 *        |
 *        v
 *   JSON report response
 *
 * The function preserves structured error payloads returned by the inference
 * backend so that API consumers receive meaningful validation or processing
 * errors.
 *
 * @param input
 *   Request payload forwarded to the case report service.
 *
 * @returns
 *   Parsed JSON response returned by the inference backend.
 *
 * @throws UpstreamServiceError
 *   When the inference service returns an unsuccessful response.
 *
 * @throws AbortError
 *   When the request exceeds the configured timeout.
 */
export async function createCaseReport(input: unknown): Promise<unknown> {
  const reportRes = await fetch(`${INFERENCE_URL}/case-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input ?? {}),
    signal: AbortSignal.timeout(CASE_REPORT_TIMEOUT_MS),
  });

  // Parse the response as JSON
  const payload: unknown = await reportRes.json().catch(() => ({ error: "Case report service error" }));
  if (!reportRes.ok) {
    throw new UpstreamServiceError(reportRes.status, payload);
  }

  return payload;
}
