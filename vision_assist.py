"""Optional, offline-after-install Florence-2 assist for PDF page analysis.

Nothing in this module contacts the network unless :func:`install_model` is
called by an explicit user action. The Hub revision is pinned and repository
Python files are deliberately excluded. Inference uses Florence classes built
into the optional Transformers runtime with ``trust_remote_code=False``.

The model produces OCR regions, not trustworthy form semantics. Returned
rectangles are evidence/suggestions only and must go through the app's review
queue; this module never edits a PDF or applies a form field.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import threading
import urllib.error
import urllib.request
from typing import Callable, Iterable, Protocol


MODEL_ID = "microsoft/Florence-2-base-ft"
# Immutable upstream commit; never silently follow `main` for weights or code.
MODEL_REVISION = "0d9634b5410c7947cf54ca344be5ad328240721f"
MODEL_SHA256 = "58757d657ff44051314c8030b68e04cb1bb618ca9a4885418f111f6fb708185a"
MODEL_FILENAME = "model.safetensors"
MODEL_BYTES = 485_000_000  # approximate display hint; GET Content-Length is authoritative
TASK_PROMPT = "<OCR_WITH_REGION>"

# Do not add model-supplied .py or pickle-based .bin files here. Florence-2 is
# supported by current Transformers releases and loaded with remote code off.
MODEL_FILES = (
    "config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    MODEL_FILENAME,
)


class VisionAssistError(RuntimeError):
    """A safe-to-display model setup, download, or analysis error."""


class DownloadCancelled(VisionAssistError):
    """Raised when the user cancels an in-progress model download."""


class CancelToken(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class DownloadProgress:
    filename: str
    file_index: int
    file_count: int
    file_bytes: int
    file_total: int | None
    total_bytes: int
    total_known_bytes: int

    @property
    def file_fraction(self) -> float | None:
        if not self.file_total:
            return None
        return min(1.0, self.file_bytes / self.file_total)


@dataclass(frozen=True)
class VisionCandidate:
    """OCR evidence rectangle in normalized page-image coordinates (0..1)."""

    text: str
    rect: tuple[float, float, float, float]
    confidence: None = None  # Florence OCR regions do not provide calibrated confidence.
    source: str = "florence2_ocr_region"


@dataclass(frozen=True)
class VisionAnalysis:
    width: int
    height: int
    candidates: tuple[VisionCandidate, ...]
    raw_text: str


ProgressCallback = Callable[[DownloadProgress], None]
OpenUrl = Callable[..., object]


def default_model_dir() -> Path:
    """Return a writable per-user cache, outside both the installer and PDF."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".cache"
    return root / "AutoPDFForm" / "models" / f"florence-2-base-ft-{MODEL_REVISION[:12]}"


def model_ready(model_dir: str | Path | None = None) -> bool:
    folder = Path(model_dir) if model_dir else default_model_dir()
    return all((folder / name).is_file() for name in MODEL_FILES)


def _check_cancel(cancel: CancelToken | None) -> None:
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("Model download cancelled. Downloaded parts are kept so you can resume later.")


def _url(filename: str) -> str:
    return f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{filename}"


def install_model(
    model_dir: str | Path | None = None,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    opener: OpenUrl | None = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Download only pinned, allow-listed files and resume valid partial files.

    Call only after the user chooses Install. The model weight file is verified
    against its pinned SHA-256 before it is atomically promoted into the cache.
    Other small assets are fetched over HTTPS from the same immutable commit.
    """
    folder = Path(model_dir) if model_dir else default_model_dir()
    folder.mkdir(parents=True, exist_ok=True)
    open_url = opener or urllib.request.urlopen
    completed_before = 0
    for index, filename in enumerate(MODEL_FILES, start=1):
        _check_cancel(cancel)
        target = folder / filename
        partial = folder / (filename + ".part")
        if target.is_file():
            if filename == MODEL_FILENAME and _sha256(target) != MODEL_SHA256:
                target.unlink()
            else:
                completed_before += target.stat().st_size
                if progress:
                    progress(DownloadProgress(filename, index, len(MODEL_FILES), target.stat().st_size,
                                             target.stat().st_size, completed_before, completed_before))
                continue

        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "AutoPDFForm-VisionAssist/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(_url(filename), headers=headers)
        try:
            response = open_url(request, timeout=45)
        except TypeError:
            # Small injectable opener convenience for tests/custom callers.
            response = open_url(request)
        except (OSError, urllib.error.URLError) as exc:
            raise VisionAssistError(f"Could not download {filename}: {exc}") from exc

        with response:
            status = getattr(response, "status", None) or response.getcode()
            if offset and status != 206:
                # Server did not honor Range. Restart rather than append a full
                # response to a partial file and corrupt the model.
                offset = 0
            response_length = _header_int(response, "Content-Length")
            if offset and status == 206:
                content_range = _header(response, "Content-Range")
                if content_range:
                    try:
                        byte_range, total = content_range.split("/", 1)
                        first, _last = byte_range.removeprefix("bytes ").split("-", 1)
                        if int(first) != offset:
                            raise ValueError("range starts at a different offset")
                        response_length = int(total)
                    except (ValueError, IndexError) as exc:
                        raise VisionAssistError(f"Server returned an invalid resume range for {filename}.") from exc
                else:
                    raise VisionAssistError(f"Server did not confirm the resume range for {filename}; retry to resume safely.")
                mode = "ab"
            else:
                if status != 200:
                    raise VisionAssistError(f"Unexpected HTTP status {status} while downloading {filename}.")
                mode = "wb"
            file_total = response_length
            actual = offset
            with partial.open(mode) as output:
                while True:
                    _check_cancel(cancel)
                    try:
                        block = response.read(chunk_size)
                    except (OSError, urllib.error.URLError) as exc:
                        raise VisionAssistError(f"Download interrupted for {filename}; retry to resume. {exc}") from exc
                    if not block:
                        break
                    output.write(block)
                    actual += len(block)
                    if progress:
                        progress(DownloadProgress(filename, index, len(MODEL_FILES), actual,
                                                 file_total, completed_before + actual - offset,
                                                 completed_before + (file_total or 0) - offset))
            if file_total is not None and actual < file_total:
                raise VisionAssistError(f"{filename} ended early; retry to resume the partial download.")
        if filename == MODEL_FILENAME and _sha256(partial) != MODEL_SHA256:
            partial.unlink(missing_ok=True)
            raise VisionAssistError("The downloaded model weights failed their pinned SHA-256 check; the file was discarded.")
        os.replace(partial, target)
        completed_before += target.stat().st_size

    if not model_ready(folder):
        raise VisionAssistError("The model download is incomplete. Retry the installation to resume it.")
    return folder


def _header(response, key: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    return headers.get(key) or headers.get(key.lower())


def _header_int(response, key: str) -> int | None:
    raw = _header(response, key)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_ocr_regions(payload: object, width: int, height: int) -> tuple[VisionCandidate, ...]:
    """Normalize Florence OCR quadrilaterals into review-only page rectangles."""
    if width <= 0 or height <= 0:
        raise ValueError("Page image dimensions must be positive.")
    if not isinstance(payload, dict):
        return ()
    result: list[VisionCandidate] = []
    labels: Iterable[object] = payload.get("labels", ())
    polygons: Iterable[object] = payload.get("quad_boxes", ())
    for label, polygon in zip(labels, polygons):
        try:
            points = list(polygon)
            xs = [float(points[i]) for i in range(0, len(points), 2)]
            ys = [float(points[i]) for i in range(1, len(points), 2)]
            if len(xs) < 2 or len(xs) != len(ys):
                continue
            x0, x1 = max(0.0, min(xs)), min(float(width), max(xs))
            y0, y1 = max(0.0, min(ys)), min(float(height), max(ys))
            if x1 <= x0 or y1 <= y0:
                continue
            text = str(label).strip()
            if not text:
                continue
            result.append(VisionCandidate(text, (x0 / width, y0 / height, x1 / width, y1 / height)))
        except (TypeError, ValueError, IndexError):
            continue
    return tuple(result)


def analyze_page(image, model_dir: str | Path | None = None, *, model=None, processor=None) -> VisionAnalysis:
    """Return normalized OCR evidence; never writes or mutates a PDF/project.

    ``model`` and ``processor`` are injectable to test result decoding. In app
    integration, call from a background worker and show candidates for manual
    acceptance. The built-in Transformers Florence implementation is used
    with remote code execution explicitly disabled.
    """
    if image is None or not hasattr(image, "size"):
        raise ValueError("Expected a PIL-compatible rendered page image.")
    width, height = map(int, image.size)
    if width <= 0 or height <= 0:
        raise ValueError("Page image dimensions must be positive.")
    folder = Path(model_dir) if model_dir else default_model_dir()
    if not model_ready(folder):
        raise VisionAssistError("Vision assist is not installed. Choose Install local Vision assist first.")
    torch_module = None
    if model is None or processor is None:
        try:
            import torch as torch_module
            from transformers import Florence2ForConditionalGeneration, Florence2Processor
        except ImportError as exc:
            raise VisionAssistError(
                "Vision assist needs the optional PyTorch and Transformers runtime. It is not included in the core app."
            ) from exc
        try:
            processor = Florence2Processor.from_pretrained(folder, local_files_only=True)
            model = Florence2ForConditionalGeneration.from_pretrained(
                folder, local_files_only=True, use_safetensors=True, trust_remote_code=False
            ).to("cpu").eval()
        except Exception as exc:
            raise VisionAssistError(f"The installed local vision model could not be loaded safely: {exc}") from exc
    try:
        rgb_image = image.convert("RGB")
        inputs = processor(text=TASK_PROMPT, images=rgb_image, return_tensors="pt")
        inference = torch_module.inference_mode() if torch_module is not None else nullcontext()
        with inference:
            generated = model.generate(**inputs, max_new_tokens=1024, num_beams=3)
        raw_text = processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(raw_text, task=TASK_PROMPT, image_size=(width, height))
        payload = parsed.get(TASK_PROMPT, parsed) if isinstance(parsed, dict) else {}
        return VisionAnalysis(width, height, parse_ocr_regions(payload, width, height), str(raw_text))
    except VisionAssistError:
        raise
    except Exception as exc:
        raise VisionAssistError(f"Vision analysis failed: {exc}") from exc

