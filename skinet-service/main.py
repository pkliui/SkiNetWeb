"""
SkiNet inference service.

POST /infer  — accepts a multipart image, returns a PNG segmentation mask.
"""

import io
import os

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Preprocessing constants (from SkiNet ios_config.yaml / main_config.yaml)
# ---------------------------------------------------------------------------
INPUT_SIZE = 256
THRESHOLD = float(os.getenv("SEGMENTATION_THRESHOLD", "0.5"))
MODEL_PATH = os.getenv("MODEL_PATH", "/models/ios_onnx.onnx")

# ---------------------------------------------------------------------------
# Load model once at startup
# ---------------------------------------------------------------------------
app = FastAPI()
session: ort.InferenceSession


@app.on_event("startup")
def load_model() -> None:
    global session
    session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    print(f"Model loaded from {MODEL_PATH}")
    print(f"Segmentation threshold: {THRESHOLD}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def preprocess(image_bytes: bytes) -> tuple:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    original_size = img.size  # (width, height)

    # Center-crop to square using full height, then resize — crops left/right only
    w, h = original_size
    crop_left = (w - h) // 2
    crop_left = max(crop_left, 0)
    crop_size = min(w, h)
    img = img.crop((crop_left, 0, crop_left + crop_size, crop_size))
    img = img.resize((INPUT_SIZE, INPUT_SIZE), resample=Image.Resampling.BILINEAR)

    arr = np.asarray(img, dtype=np.float32) / 255.0
    per_image_mean = arr.mean(axis=(0, 1), keepdims=True)
    per_image_std = arr.std(axis=(0, 1), keepdims=True).clip(min=1e-7)
    arr = (arr - per_image_mean) / per_image_std
    arr = arr.transpose(2, 0, 1)
    return arr[None, ...], original_size, crop_left


def postprocess(output: np.ndarray, original_size: tuple, crop_left: int) -> bytes:
    """[1, 1, 256, 256] float32 → PNG bytes (mask placed back into original image coordinates)."""
    prob = output[0, 0]
    mask = (prob >= THRESHOLD).astype(np.uint8) * 255
    w, h = original_size
    crop_size = min(w, h)
    # Resize mask back to the square crop dimensions
    mask_crop = Image.fromarray(mask, mode="L").resize((crop_size, crop_size), resample=Image.Resampling.NEAREST)
    # Paste into a black canvas at original dimensions so mask aligns with original image
    canvas = Image.new("L", original_size, 0)
    canvas.paste(mask_crop, (crop_left, 0))
    png_bytes = io.BytesIO()
    canvas.save(png_bytes, format="PNG")
    return png_bytes.getvalue()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.post("/infer")
async def infer(image: UploadFile = File(...)) -> Response:
    if image.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Only JPEG and PNG images are supported")

    image_bytes = await image.read()
    try:
        tensor, original_size, crop_left = preprocess(image_bytes)
        output = session.run(["mask_prob"], {"image": tensor})[0]
        mask_png = postprocess(output, original_size, crop_left)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=mask_png, media_type="image/png")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
