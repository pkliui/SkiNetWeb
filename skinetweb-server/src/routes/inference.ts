/**
 * HTTP routing layer for inference-related API endpoints.
 *
 * This module defines the public API surface exposed to clients and coordinates
 * request processing through middleware and the inference service layer.
 *
 * Responsibilities:
 *
 * - Define HTTP endpoints for segmentation and case reporting.
 * - Apply request-level concurrency protection for expensive operations.
 * - Validate and process incoming uploads.
 * - Delegate inference operations to the service layer.
 * - Translate service-layer errors into HTTP responses.
 *
 * Architectural boundaries:
 *
 * The router does not contain inference logic or outbound service communication.
 * Those concerns are delegated to inferenceService.ts. This keeps HTTP handling
 * separate from integration logic and allows the inference backend to evolve
 * independently.
 *
 * Resource protection:
 *
 * Segmentation and case-report operations have independent concurrency limits
 * because they represent different workloads and may consume different backend
 * resources.
 */

import { Router, type Request, type Response } from "express";

import { MAX_CASE_REPORT_CONCURRENCY, MAX_SEGMENT_CONCURRENCY } from "../config.js";
import { createConcurrencyMiddleware } from "../middleware/concurrency.js";
import { parseImageUpload } from "../middleware/upload.js";
import { createCaseReport, segmentImage } from "../services/inferenceService.js";
import { sendServiceError } from "../utils/errors.js";

export const inferenceRouter = Router();

const limitSegmentConcurrency = createConcurrencyMiddleware(
  MAX_SEGMENT_CONCURRENCY,
  "Segmentation service is busy. Please retry shortly.",
);

const limitCaseReportConcurrency = createConcurrencyMiddleware(
  MAX_CASE_REPORT_CONCURRENCY,
  "Case report service is busy. Please retry shortly.",
);

inferenceRouter.post("/api/segment", limitSegmentConcurrency, parseImageUpload, async (req: Request, res: Response) => {
  try {
    if (!req.file) {
      res.status(400).json({ error: "No image file provided" });
      return;
    }

    // The inference service returns the segmentation mask as PNG bytes.
    res.set("Content-Type", "image/png");
    res.send(await segmentImage(req.file));
  } catch (error) {
    sendServiceError(res, error, {
      timedOut: "Inference service timed out",
      unavailable: "Inference service unavailable",
    });
  }
});

inferenceRouter.post("/api/case-report", limitCaseReportConcurrency, async (req: Request, res: Response) => {
  try {
    res.json(await createCaseReport(req.body));
  } catch (error) {
    sendServiceError(res, error, {
      timedOut: "Case report service timed out",
      unavailable: "Case report service unavailable",
    });
  }
});
