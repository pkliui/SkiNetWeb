import asyncio
import io
import logging
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from starlette.datastructures import Headers, UploadFile

import main
from main import (
    INPUT_SIZE,
    SEGMENTATION_THRESHOLD,
    _read_capped,
    _run_inference,
    _run_with_slow_warning,
    infer,
    postprocess,
    preprocess,
)


def _solid_jpeg_bytes(width: int, height: int, color=(200, 100, 50)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# preprocess — center-crop must center on whichever axis is longer
# ---------------------------------------------------------------------------


def test_preprocess_square_image_is_not_cropped():
    arr, original_size, crop_left, crop_top = preprocess(_solid_jpeg_bytes(300, 300))

    assert original_size == (300, 300)
    assert crop_left == 0
    assert crop_top == 0
    assert arr.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)


def test_preprocess_landscape_crops_left_and_right_only():
    # width > height: crop should trim the sides, not the top/bottom.
    arr, original_size, crop_left, crop_top = preprocess(_solid_jpeg_bytes(400, 200))

    assert original_size == (400, 200)
    assert crop_left == 100  # (400 - 200) // 2
    assert crop_top == 0
    assert arr.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)


def test_preprocess_portrait_crops_top_and_bottom_only():
    # Regression test: height > width (e.g. an unrotated portrait iPhone photo)
    # used to always crop from y=0, silently discarding the bottom of the image
    # instead of centering. width should now be untouched and the vertical crop
    # should be centered, symmetric to the landscape case above.
    arr, original_size, crop_left, crop_top = preprocess(_solid_jpeg_bytes(200, 400))

    assert original_size == (200, 400)
    assert crop_left == 0
    assert crop_top == 100  # (400 - 200) // 2
    assert arr.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)


# ---------------------------------------------------------------------------
# preprocess — EXIF orientation must be applied before size/crop are computed
# ---------------------------------------------------------------------------


def _solid_jpeg_bytes_with_exif_orientation(width: int, height: int, orientation: int, color=(200, 100, 50)) -> bytes:
    """A JPEG whose raw pixel buffer is (width, height) but carries an EXIF
    Orientation tag telling viewers to rotate it — mimics a phone photo shot
    in portrait, where the sensor always writes its native (landscape) shape
    and the rotation needed for display is recorded as metadata rather than
    baked into the pixels.
    """
    img = Image.new("RGB", (width, height), color)
    exif = img.getexif()
    exif[0x0112] = orientation  # 274 = Orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_preprocess_swaps_size_for_90_degree_exif_orientation():
    # Raw buffer is landscape (400x200); Orientation=6 means "rotate 90 CW to
    # display correctly", so the corrected image is portrait (200x400). If
    # `preprocess` didn't apply exif_transpose before reading `.size`, this
    # would report the raw (400, 200) instead, and crop_left/crop_top would
    # be computed against the wrong axis.
    arr, original_size, crop_left, crop_top = preprocess(
        _solid_jpeg_bytes_with_exif_orientation(400, 200, orientation=6)
    )

    assert original_size == (200, 400)
    assert crop_left == 0
    assert crop_top == 100  # (400 - 200) // 2, centered on the corrected height
    assert arr.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)


def test_preprocess_untouched_for_normal_exif_orientation():
    # Orientation=1 ("normal") is a no-op for exif_transpose — regression
    # guard so the swap above isn't accidentally applied unconditionally.
    arr, original_size, crop_left, crop_top = preprocess(
        _solid_jpeg_bytes_with_exif_orientation(400, 200, orientation=1)
    )

    assert original_size == (400, 200)
    assert crop_left == 100
    assert crop_top == 0


def test_preprocess_postprocess_roundtrip_respects_exif_rotation():
    """End-to-end regression: the mask canvas returned by postprocess must be
    sized and offset from the EXIF-corrected orientation — matching what a
    browser renders, since browsers apply EXIF rotation automatically when
    displaying the original upload — not the raw sensor-native buffer that
    `Image.open` alone would report.
    """
    jpeg_bytes = _solid_jpeg_bytes_with_exif_orientation(400, 200, orientation=6)
    _, original_size, crop_left, crop_top = preprocess(jpeg_bytes)
    png_bytes = postprocess(_full_mask_output(), original_size, crop_left, crop_top)
    mask = _mask_array(png_bytes)

    assert original_size == (200, 400)
    assert mask.shape == (400, 200)  # (h, w) — matches the corrected, not raw, orientation
    assert (mask[:100, :] == 0).all()  # top margin, outside the crop
    assert (mask[100:300, :] == 255).all()  # centered crop
    assert (mask[300:, :] == 0).all()  # bottom margin, outside the crop


# ---------------------------------------------------------------------------
# postprocess — the returned mask must be pasted back at (crop_left, crop_top)
# ---------------------------------------------------------------------------


def _full_mask_output() -> np.ndarray:
    """A model output that's above SEGMENTATION_THRESHOLD everywhere, shape (1, 1, INPUT_SIZE, INPUT_SIZE)."""
    return np.full((1, 1, INPUT_SIZE, INPUT_SIZE), SEGMENTATION_THRESHOLD + 1.0, dtype=np.float32)


def _mask_array(png_bytes: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png_bytes)))


def test_postprocess_places_mask_at_horizontal_offset_for_landscape():
    original_size = (400, 200)  # (w, h)
    png_bytes = postprocess(_full_mask_output(), original_size, crop_left=100, crop_top=0)
    mask = _mask_array(png_bytes)

    assert mask.shape == (200, 400)  # (h, w)
    assert (mask[:, :100] == 0).all()  # left margin, outside the crop
    assert (mask[:, 100:300] == 255).all()  # the crop itself, full height
    assert (mask[:, 300:] == 0).all()  # right margin, outside the crop


def test_postprocess_places_mask_at_vertical_offset_for_portrait():
    # Regression test for the same bug as above, from the postprocess side:
    # pasting always at y=0 would put mask content in rows 0-199 instead of
    # the correct centered rows 100-299.
    original_size = (200, 400)  # (w, h)
    png_bytes = postprocess(_full_mask_output(), original_size, crop_left=0, crop_top=100)
    mask = _mask_array(png_bytes)

    assert mask.shape == (400, 200)  # (h, w)
    assert (mask[:100, :] == 0).all()  # top margin, outside the crop
    assert (mask[100:300, :] == 255).all()  # the crop itself, full width
    assert (mask[300:, :] == 0).all()  # bottom margin, outside the crop


def test_preprocess_postprocess_roundtrip_portrait_covers_centered_square():
    """End-to-end: a portrait image's mask should be centered vertically, not clipped to the top."""
    _, original_size, crop_left, crop_top = preprocess(_solid_jpeg_bytes(200, 400))
    png_bytes = postprocess(_full_mask_output(), original_size, crop_left, crop_top)
    mask = _mask_array(png_bytes)

    nonzero_rows = np.where((mask > 0).any(axis=1))[0]
    assert nonzero_rows.min() == 100
    assert nonzero_rows.max() == 299


def test_postprocess_square_image_fills_entire_canvas():
    # No margin to crop on either axis, so the full canvas should be mask.
    original_size = (300, 300)
    png_bytes = postprocess(_full_mask_output(), original_size, crop_left=0, crop_top=0)
    mask = _mask_array(png_bytes)

    assert mask.shape == (300, 300)
    assert (mask == 255).all()


def test_postprocess_below_threshold_everywhere_yields_empty_mask():
    output = np.full((1, 1, INPUT_SIZE, INPUT_SIZE), SEGMENTATION_THRESHOLD - 0.01, dtype=np.float32)
    png_bytes = postprocess(output, original_size=(300, 300), crop_left=0, crop_top=0)
    mask = _mask_array(png_bytes)

    assert (mask == 0).all()


def test_postprocess_threshold_is_inclusive():
    # prob == SEGMENTATION_THRESHOLD must count as mask (uses >=, not >).
    output = np.full((1, 1, INPUT_SIZE, INPUT_SIZE), SEGMENTATION_THRESHOLD, dtype=np.float32)
    png_bytes = postprocess(output, original_size=(300, 300), crop_left=0, crop_top=0)
    mask = _mask_array(png_bytes)

    assert (mask == 255).all()


def test_postprocess_mixed_probabilities_produce_binary_mask():
    output = np.zeros((1, 1, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
    output[0, 0, : INPUT_SIZE // 2, :] = SEGMENTATION_THRESHOLD + 1.0  # top half above threshold
    png_bytes = postprocess(output, original_size=(300, 300), crop_left=0, crop_top=0)
    mask = _mask_array(png_bytes)

    assert set(np.unique(mask)) <= {0, 255}
    assert (mask[: mask.shape[0] // 2, :] == 255).all()
    assert (mask[mask.shape[0] // 2 :, :] == 0).all()


def test_postprocess_returns_grayscale_png_bytes():
    png_bytes = postprocess(_full_mask_output(), original_size=(300, 300), crop_left=0, crop_top=0)

    assert isinstance(png_bytes, bytes)
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.mode == "L"
    assert img.size == (300, 300)


# ---------------------------------------------------------------------------
# _run_inference — preprocess -> session.run -> postprocess glue
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for ort.InferenceSession that records the call and returns a fixed output."""

    def __init__(self, output: np.ndarray):
        self._output = output
        self.calls = []

    def run(self, output_names, feed):
        self.calls.append((output_names, feed))
        return [self._output]


def test_run_inference_feeds_session_with_expected_tensor_names():
    fake_session = _FakeSession(_full_mask_output())

    _run_inference(fake_session, _solid_jpeg_bytes(300, 300))

    assert len(fake_session.calls) == 1
    output_names, feed = fake_session.calls[0]
    assert output_names == ["mask_prob"]
    assert list(feed.keys()) == ["image"]
    assert feed["image"].shape == (1, 3, INPUT_SIZE, INPUT_SIZE)


def test_run_inference_returns_postprocessed_png():
    fake_session = _FakeSession(_full_mask_output())

    # Landscape image so the crop offset is non-trivial, exercising the full
    # preprocess -> session.run -> postprocess round trip end to end.
    png_bytes = _run_inference(fake_session, _solid_jpeg_bytes(400, 200))
    mask = _mask_array(png_bytes)

    assert mask.shape == (200, 400)  # (h, w), matches original_size
    assert (mask[:, 100:300] == 255).all()  # inside the centered crop
    assert (mask[:, :100] == 0).all()  # outside the crop, untouched by the mask
    assert (mask[:, 300:] == 0).all()


def test_run_inference_propagates_preprocess_errors_without_calling_session():
    fake_session = _FakeSession(_full_mask_output())

    with pytest.raises(UnidentifiedImageError):
        _run_inference(fake_session, b"not an image")

    assert fake_session.calls == []


# ---------------------------------------------------------------------------
# Allowed formats — declared Content-Type is checked first, the real bytes second
# ---------------------------------------------------------------------------


def _solid_image_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 100, 50)).save(buf, format=fmt)
    return buf.getvalue()


def _upload(data: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="upload", headers=Headers({"content-type": content_type}))


def _request_with_session(session: _FakeSession) -> SimpleNamespace:
    # `infer` only reads `request.state.session`, so a namespace stands in for a Request.
    return SimpleNamespace(state=SimpleNamespace(session=session))


def test_preprocess_accepts_png():
    arr, original_size, _, _ = preprocess(_solid_image_bytes("PNG"))

    assert arr.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    assert original_size == (32, 32)


def test_preprocess_rejects_valid_image_in_disallowed_format():
    # A well-formed GIF decodes fine with an unrestricted Image.open; it must not here.
    with pytest.raises(UnidentifiedImageError):
        preprocess(_solid_image_bytes("GIF"))


def test_infer_rejects_gif_mislabelled_as_png():
    fake_session = _FakeSession(_full_mask_output())
    upload = _upload(_solid_image_bytes("GIF"), "image/png")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(infer(_request_with_session(fake_session), upload))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Could not process the uploaded image"
    assert fake_session.calls == []


# ---------------------------------------------------------------------------
# _read_capped — enforces MAX_UPLOAD_BYTES against bytes actually received
# ---------------------------------------------------------------------------


def test_read_capped_returns_full_content_under_limit():
    data = b"x" * 500
    upload = UploadFile(file=io.BytesIO(data), filename="small.jpg")

    result = asyncio.run(_read_capped(upload, max_bytes=1000))

    assert result == data


def test_read_capped_allows_content_exactly_at_limit():
    data = b"x" * 1000
    upload = UploadFile(file=io.BytesIO(data), filename="exact.jpg")

    result = asyncio.run(_read_capped(upload, max_bytes=1000))

    assert result == data


def test_read_capped_rejects_content_over_limit():
    data = b"x" * 1001
    upload = UploadFile(file=io.BytesIO(data), filename="big.jpg")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_read_capped(upload, max_bytes=1000))

    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# _run_with_slow_warning — purely informational, never cancels the coroutine
# ---------------------------------------------------------------------------


def test_slow_warning_logs_periodically_while_running_and_returns_result(caplog):
    async def slow():
        await asyncio.sleep(0.15)
        return "done"

    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            _run_with_slow_warning(slow(), request_id="abc123", warn_every=0.05)
        )

    assert result == "done"
    warnings = [r.getMessage() for r in caplog.records]
    assert sum("still running" in msg for msg in warnings) >= 2
    assert all("abc123" in msg for msg in warnings if "still running" in msg)


def test_slow_warning_silent_when_faster_than_warn_interval(caplog):
    async def fast():
        return "ok"

    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            _run_with_slow_warning(fast(), request_id="xyz", warn_every=10)
        )

    assert result == "ok"
    assert not any("still running" in r.getMessage() for r in caplog.records)


def test_slow_warning_propagates_exceptions_from_the_wrapped_coroutine():
    async def boom():
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        asyncio.run(_run_with_slow_warning(boom(), request_id="err", warn_every=1))
