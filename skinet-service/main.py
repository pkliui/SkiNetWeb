"""
SkiNet inference service.

POST /infer  - accepts a multipart image, returns a PNG segmentation mask.
POST /case-report - generate a report from the pre-computed segmentation metrics.
"""

import asyncio
import io
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
import logging

from logging_setup import stdout_logging, file_logging
from reporting import (
    CaseReport,
    CaseReportRequest,
    ProviderStatus,
    check_provider_status,
    create_default_resolver,
    generate_case_report,
)
from settings import (
    INFER_SLOW_WARN_SECONDS,
    INPUT_SIZE,
    MAX_CASE_REPORT_CONCURRENCY,
    MAX_UPLOAD_BYTES,
    MODEL_PATH,
    NORM_MEAN,
    NORM_STD,
    ORT_INTRA_OP_NUM_THREADS,
    SEGMENTATION_THRESHOLD,
)

stdout_logging(logging.INFO)
file_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load model once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load the ONNX model and set up the shared LLM client once at process startup.

    FastAPI's `lifespan` context manager: everything before `yield` runs once before
    the app starts serving requests; everything after `yield` runs once after it stops.
    The following objects are set up here:

    - `session` (an ONNX Runtime `InferenceSession`) - loading the model from disk
      is expensive so we do it only once before the app starts serving requests.
    - `session.run()` is thread-safe on `CPUExecutionProvider`, that is why concurrent requests
      can safely share only one instance
    - `client` (an `httpx.AsyncClient`) - reuses pooled connections to the LLM
      provider across `/case-report` calls instead of a new TCP+TLS handshake
      per request

    `client` is exposed via `application.state.llm_http_client`, read directly off
    `http_request.app.state` by `case_report`, `session` is instead yielded as
    `{"session": session}` and `infer` passes it explicitly into `_run_inference` as an argument.
    """
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = ORT_INTRA_OP_NUM_THREADS

    session = ort.InferenceSession(MODEL_PATH,
                                   sess_options=session_options,
                                   providers=["CPUExecutionProvider"])
    logger.info(f"Model loaded from {MODEL_PATH}")
    logger.info(f"ORT intra_op_num_threads={ORT_INTRA_OP_NUM_THREADS}")

    # A single client is instantiated for the lifetime of the process, rather than
    # per request, so that report requests reuse pooled connections to the LLM
    # provider instead of incurring a new TCP + TLS handshake on every call.
    # Per-request and per-attempt timeouts are applied explicitly at the call site.
    #
    # Both limits equal MAX_CASE_REPORT_CONCURRENCY (the Express-enforced ceiling on
    # concurrent /case-report requests reaching this service) with no extra headroom.
    # httpcore closes and releases a failed/cancelled request's connection
    # synchronously, before the exception reaches calling code (see
    # httpcore's AsyncConnectionPool.handle_async_request), so a retry after our own
    # asyncio.wait_for-based per-attempt timeout never needs a second simultaneous
    # slot for the same logical request. Verified empirically: 25 trials of N=5
    # concurrent requests, each cancelled mid-flight and immediately retried against
    # a pool capped at exactly N with zero headroom, produced zero PoolTimeouts.
    async with httpx.AsyncClient(
        limits=httpx.Limits(
            max_keepalive_connections=MAX_CASE_REPORT_CONCURRENCY,
            max_connections=MAX_CASE_REPORT_CONCURRENCY,
        ),
    ) as client:
        # Sequence that makes this assignment work:
        # 1. `app = FastAPI(lifespan=lifespan)` below runs FastAPI.__init__ ->
        #    Starlette.__init__ -> `self.state = State()`. The global `app`
        #    object exists at that point, already holding an empty `.state`.
        # 2. Later, uvicorn's `lifespan.startup` message arrives -> Starlette
        #    calls `self.lifespan_context(app)`, passing that same object in
        #    as this function's `application` parameter.
        # 3. This function body runs top-to-bottom, and the line below just
        #    mutates the dict inside the `State` object created in step 1.
        application.state.llm_http_client = client

        # Starlette merges whatever mapping is yielded here into the ASGI scope's
        # state dict once at startup, then shallow-copies it onto `request.state`
        # per request; `request.state` exposes that dict's keys as attributes
        # (Starlette's `State.__getattr__`), so the "session" key below is what
        # makes `request.state.session` resolve in `/infer` (see `infer`).
        yield {"session": session}

app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, status code, and latency for every HTTP request."""
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


def preprocess(image_bytes: bytes) -> tuple:
    """Decode, center-crop to square, resize, and normalize an image for the model.

    Centers the crop on whichever axis is longer: for width >= height (e.g.
    landscape ski photos) it keeps the full height and trims equal margins off
    the left/right; for height > width (e.g. a portrait iPhone photo, which the
    frontend uploads unmodified — see `skinetweb-ui/src/components/UploadZone.tsx`)
    it keeps the full width and trims equal margins off the top/bottom instead.
    `crop_left`/`crop_top` are returned so `postprocess` can paste the resulting
    mask back at the correct offset in the original image.

    Applies `ImageOps.exif_transpose` before reading `.size`. A phone sensor
    always writes pixels in one fixed native orientation; the rotation needed
    for correct display is recorded separately as an EXIF `Orientation` tag,
    which `Image.open` alone ignores. Without the transpose, `.size` — and
    therefore `crop_left`/`crop_top`/the crop axis below — would always reflect the
    raw sensor orientation instead of what the browser (EXIF-aware) displays,
    and `postprocess` would position the mask and size its canvas to match this raw sensor orientation,
    misaligning it with the original image on the frontend (see `maskToBinary`
    in `skinetweb-ui/src/components/ResultsGrid.tsx`, which trusts the mask's
    size without validating it). No-op for images with no `Orientation` tag (e.g.
    the dataset examples in `skinetweb-ui/public/examples/`).

    Args:
        image_bytes: Raw, still-encoded (JPEG/PNG) file content — size-capped
            but otherwise unvalidated. Originates from the multipart upload in
            the `/infer` endpoint, read via `_read_capped` (which only bounds
            total size, MAX_UPLOAD_BYTES), then passed through `_run_inference`
            without modification. This function is the first point where the
            bytes are decoded — any invalid/corrupt image is flagged here as
            `UnidentifiedImageError`, `ValueError`, `OSError`, or (for an
            image whose declared dimensions decode to more than
            `2 * Image.MAX_IMAGE_PIXELS`) `Image.DecompressionBombError`.

    Returns:
        arr: float32 NCHW tensor (1, 3, INPUT_SIZE, INPUT_SIZE), normalized.
        original_size: (width, height) of the input image, pre-crop.
        crop_left: x-offset in original-image pixels where the square crop began.
        crop_top: y-offset in original-image pixels where the square crop began.
    """
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    original_size = img.size  # (width, height)

    # Center-crop to square on whichever axis is longer, then resize.
    w, h = original_size
    crop_size = min(w, h)
    crop_left = max((w - crop_size) // 2, 0)
    crop_top = max((h - crop_size) // 2, 0)
    img = img.crop((crop_left, crop_top, crop_left + crop_size, crop_top + crop_size))
    img = img.resize((INPUT_SIZE, INPUT_SIZE), resample=Image.Resampling.BILINEAR)

    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - NORM_MEAN) / NORM_STD
    arr = arr.transpose(2, 0, 1)[np.newaxis]  # HWC → NCHW: (1, 3, 256, 256)
    return arr, original_size, crop_left, crop_top


def postprocess(output: np.ndarray, original_size: tuple, crop_left: int, crop_top: int) -> bytes:
    """Threshold the model's probability map and paste it back into original image coordinates.

    Inverse of `preprocess`: thresholds the per-pixel probabilities into a binary
    mask, resizes that mask from INPUT_SIZE back up to the square crop's original
    pixel size, then pastes it into a black (all-zero) canvas at `original_size`
    using the same `crop_left`/`crop_top` offset `preprocess` cropped from — so the
    mask lines up with the un-cropped original image the frontend displays.

    Args:
        output: Model output, float32 array of shape (1, 1, INPUT_SIZE, INPUT_SIZE)
            with per-pixel probabilities in [0, 1] (`session.run(["mask_prob"], ...)`).
        original_size: (width, height) of the input image before cropping, as
            returned by `preprocess`.
        crop_left: x-offset in original-image pixels where the square crop began,
            as returned by `preprocess`.
        crop_top: y-offset in original-image pixels where the square crop began,
            as returned by `preprocess`.

    Returns:
        PNG-encoded bytes of an "L" (8-bit grayscale) image at `original_size`,
        with mask pixels set to 255 and everything outside the pasted crop set to 0.
    """
    # Drop the batch and channel dims (both size 1) to get a plain (H, W)
    # probability map, as Image.fromarray(mode="L") below expects 2D input.
    prob = output[0, 0]
    mask = (prob >= SEGMENTATION_THRESHOLD).astype(np.uint8) * 255
    w, h = original_size
    crop_size = min(w, h)
    # Resize mask back to the square crop dimensions
    mask_crop = Image.fromarray(mask, mode="L").resize((crop_size, crop_size), resample=Image.Resampling.NEAREST)
    # Paste into a black canvas at original dimensions so mask aligns with original image
    canvas = Image.new("L", original_size, 0)
    canvas.paste(mask_crop, (crop_left, crop_top))
    # PIL's Image.save() only writes to a path or file-like object — there's no
    # method that returns encoded bytes directly — so BytesIO stands in as an
    # in-memory file to PNG-encode into without touching disk.
    png_bytes = io.BytesIO()
    canvas.save(png_bytes, format="PNG")
    return png_bytes.getvalue()


def _run_inference(session: ort.InferenceSession, image_bytes: bytes) -> bytes:
    """Run the full `preprocess` -> ONNX `session.run` -> `postprocess` pipeline.

    Plain (non-async) function: everything inside is a blocking, synchronous
    call (PIL, then the ONNX forward pass) with nothing to `await`, so callers
    must dispatch it via `run_in_threadpool` — see the `/infer` endpoint.

    Feeds `session` (created once at startup by `lifespan`, passed in via
    `request.state.session`) by calling `session.run(["mask_prob"], {"image": preprocessed_image})`,
    where `preprocessed_image` is the normalized NCHW array `preprocess` returns, `"image"` and
    `"mask_prob"` are the ONNX model's input/output tensor names, fixed when
    the model was exported (see the training repo's `export_onnx.py`) and
    must match exactly for `session.run` to find the right tensors,
    `"mask_prob"` is the sigmoid-activated per-pixel foreground probability
    that `postprocess` thresholds.

    Args:
        session: The loaded ONNX Runtime session, sourced from
            `request.state.session` by the `/infer` endpoint.
        image_bytes: Raw, still-encoded (JPEG/PNG) file content, as passed to
            `preprocess`.

    Returns:
        PNG-encoded mask bytes, as returned by `postprocess`.
    """
    preprocessed_image, original_size, crop_left, crop_top = preprocess(image_bytes)
    output = session.run(["mask_prob"], {"image": preprocessed_image})[0]
    return postprocess(output, original_size, crop_left, crop_top)


async def _run_with_slow_warning(inference_coroutine, request_id: str, warn_every: float = INFER_SLOW_WARN_SECONDS):
    """Await `inference_coroutine`, logging every `warn_every` seconds while it's still running.

    Purely informational: checks in repeatedly using `asyncio.wait(..., timeout=...)` rather than
    `asyncio.wait_for`, so it never cancels `inference_coroutine`.

    Args:
        inference_coroutine: The awaitable to run to completion, unmodified.
            In `infer`, this is `run_in_threadpool(_run_inference, ...)`.
        request_id: The first 8 hex characters of a `uuid.uuid4()`, generated
            by `infer` as `uuid.uuid4().hex[:8]`. Used only to tag the
            periodic log lines, so concurrent slow requests can be told
            apart in the logs.
        warn_every: Seconds between "still running" log lines; defaults to
            `INFER_SLOW_WARN_SECONDS`.

    Returns:
        Whatever `inference_coroutine` returns.
    """
    # Wrapped into a Task once, up front: asyncio.wait() below needs a Future/Task rather than
    # a bare coroutine (passing one raises `TypeError: Passing coroutines is forbidden`), and
    # re-wrapping inference_coroutine on each loop iteration would fail too, since a coroutine
    # object can only be scheduled once (`RuntimeError: cannot reuse already awaited coroutine`).
    task = asyncio.ensure_future(inference_coroutine)
    elapsed = 0.0
    while True:
        done, _ = await asyncio.wait({task}, timeout=warn_every)
        if task in done:
            return task.result()
        elapsed += warn_every
        logger.info("Inference request %s still running after %.0fs", request_id, elapsed)


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read `upload` in chunks, aborting with 413 once `max_bytes` is exceeded.

    `Content-Length` isn't trustworthy on its own (a client can omit it, lie
    about it, or use chunked transfer-encoding), so the cap is enforced against
    bytes actually received rather than the declared header. Neither FastAPI's
    `File()` nor the installed Starlette version (0.41.3, pinned via
    requirements.txt) expose a size-limit hook for multipart uploads, so this
    is enforced by hand.
    """
    chunks = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Image exceeds maximum upload size")
        chunks.append(chunk)
    # Collect chunks and join once at the end rather than `buf += chunk`: bytes
    # are immutable, so repeated += would reallocate and copy the whole buffer
    # on every chunk (O(n^2)); join() copies each chunk exactly once (O(n)).
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/infer")
async def infer(request: Request, image: UploadFile = File(...)) -> Response:
    """Run segmentation on an uploaded image and return the mask as a PNG.

    Accepts a multipart-form upload (field ``image``) of a JPEG or PNG.

    The `content_type` check below only reads the `Content-Type` header the
    client sent with the file; it does not look at the file's actual bytes.
    The upstream Node proxy performs the same header check before forwarding.
    So a mismatched or corrupt file can still pass here, and fails only
    later, when PIL tries to decode it in `preprocess`. Such failures
    surface as a 400 from the `try`/`except` block below.

    Size is capped at `MAX_UPLOAD_BYTES` by `_read_capped`.

    Inference is CPU-bound (PIL decode/resize + ONNX Runtime), so it is
    dispatched via `run_in_threadpool` to avoid blocking the async event
    loop that serves other concurrent requests.

    Concurrency model — the two `await` points below vs. the GIL per stage:

        event loop thread                    worker thread (different from the event loop, possibly, but not necessarily, on another CPU)
        ------------------                   -------------
        await _read_capped()
        await run_in_threadpool()  --->       preprocess()
                                                 Image.open        GIL held
        (free for other requests)               crop / resize     GIL: mixed
                                               session.run()       GIL released
                                               postprocess()
                                                 fromarray / new   GIL held
                                                 canvas.save (PNG) GIL released
        await resumes               <---
        return Response()

    Runs on `CPUExecutionProvider`, so host core count is the real ceiling on
    concurrent throughput — see `ORT_INTRA_OP_NUM_THREADS` above `lifespan`.

    Error handling distinguishes three cases:
    - Unreadable/corrupt image -> 400 "Could not process the uploaded
      image", logged at warning level since it's an expected, client-caused
      outcome.
    - Oversized upload -> 413, raised by `_read_capped` before any decode is
      attempted.
    - Anything else (e.g. a model/runtime bug) -> 500, logged with a full
      traceback since it indicates a bug in this service.
    """
    if image.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Only JPEG and PNG images are supported")

    image_bytes = await _read_capped(image, MAX_UPLOAD_BYTES)
    request_id = uuid.uuid4().hex[:8]
    try:
        # pushes PIL decode/resize and the ONNX forward pass off the event-loop thread onto the worker threadpool
        #
        # Purely informational: _run_with_slow_warning checks in repeatedly using
        # `asyncio.wait(..., timeout=...)` rather than `asyncio.wait_for` because the latter
        # would only cancel the underlying asyncio Task and not the underlying OS thread
        # running the blocking PIL/ONNX work, assuming `inference_coroutine` is wrapped in a
        # `run_in_threadpool` call (as it is here).
        mask_png = await _run_with_slow_warning(
            run_in_threadpool(_run_inference, request.state.session, image_bytes), request_id
        )
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError) as exc:
        logger.warning("Rejected unprocessable image upload: %s", exc)
        raise HTTPException(status_code=400, detail="Could not process the uploaded image") from exc
    except Exception as exc:
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail="Internal error during inference") from exc

    return Response(content=mask_png, media_type="image/png")


@app.post("/case-report", response_model=CaseReport)
async def case_report(request: CaseReportRequest, http_request: Request) -> CaseReport:
    """Generate an AI case report from the pre-computed segmentation metrics.

    Validation is FastAPI's job, not this function's: the ``CaseReportRequest``
    body and the ``response_model=CaseReport`` return value are both validated
    by FastAPI. This function just calls ``generate_case_report`` and hands
    back whatever it returns.

    ``http_request`` is here only to reach the pooled LLM client that
    ``lifespan`` put on ``app.state`` (a ``Request``-typed parameter doesn't
    consume the body, so ``request`` still gets the full JSON payload).
    ``http_request.app`` is the same ``application`` object ``lifespan`` set
    ``state.llm_http_client`` on, and the ASGI lifespan handshake guarantees
    that write completes before uvicorn accepts the first request — so this
    read can never race it.

    Called by the Node proxy's ``createCaseReport`` (inferenceService.ts),
    which itself is invoked from the ``/api/case-report`` Express route.
    """
    try:
        return await generate_case_report(request, http_client=http_request.app.state.llm_http_client)
    except Exception as exc:
        logger.exception("Case report generation failed")
        raise HTTPException(status_code=500, detail="Internal error during report generation") from exc


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": create_default_resolver().resolve() is not None,
    }


@app.get("/case-report/status", response_model=ProviderStatus)
async def case_report_status() -> ProviderStatus:
    provider = create_default_resolver().resolve()
    if provider is None:
        return ProviderStatus(llmConfigured=False, reachable=False, reason="llm-not-configured")

    return await check_provider_status(provider)
