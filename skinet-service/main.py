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
from PIL import Image

# ---------------------------------------------------------------------------
# Preprocessing constants (from SkiNet ios_config.yaml / main_config.yaml)
# ---------------------------------------------------------------------------
INPUT_SIZE = 512
MEAN = np.array([0.699, 0.556, 0.5121], dtype=np.float32)
STD  = np.array([0.1576, 0.1562, 0.1706], dtype=np.float32)
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

def preprocess(image_bytes: bytes) -> np.ndarray:
    """PIL image bytes → [1, 3, 512, 512] float32 numpy array."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((INPUT_SIZE, INPUT_SIZE), Image.LANCZOS)
    arr = np.array(img, dtype=np.float32) / 255.0   # HWC, [0, 1]
    arr = (arr - MEAN) / STD                          # normalise
    arr = arr.transpose(2, 0, 1)                      # HWC → CHW
    return arr[np.newaxis]                            # add batch dim


def postprocess(output: np.ndarray) -> bytes:
    """[1, 1, 512, 512] float32 → PNG bytes (binary mask)."""
    prob = output[0, 0]                                   # [512, 512]
    mask = (prob >= THRESHOLD).astype(np.uint8) * 255
    png_bytes = io.BytesIO()
    Image.fromarray(mask, mode="L").save(png_bytes, format="PNG")
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
        tensor = preprocess(image_bytes)
        output = session.run(["mask_prob"], {"image": tensor})[0]
        mask_png = postprocess(output)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=mask_png, media_type="image/png")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
