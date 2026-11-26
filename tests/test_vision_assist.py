import hashlib
from pathlib import Path

import pytest

import vision_assist as vision


class Token:
    def __init__(self):
        self.cancelled = False

    def is_set(self):
        return self.cancelled


class Response:
    def __init__(self, data, status=200, start=0):
        self.data = data[start:]
        self.status = status
        self.headers = {
            "Content-Length": str(len(self.data)),
            **({"Content-Range": f"bytes {start}-{len(data)-1}/{len(data)}"} if status == 206 else {}),
        }
        self.cursor = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def getcode(self):
        return self.status

    def read(self, count=-1):
        if count < 0:
            count = len(self.data)
        part = self.data[self.cursor:self.cursor + count]
        self.cursor += len(part)
        return part


def prepare_expected_hash(monkeypatch, weights):
    monkeypatch.setattr(vision, "MODEL_SHA256", hashlib.sha256(weights).hexdigest())


def test_installer_downloads_allow_list_with_revision_and_progress(tmp_path, monkeypatch):
    payloads = {name: (b"weight" if name == vision.MODEL_FILENAME else name.encode()) for name in vision.MODEL_FILES}
    prepare_expected_hash(monkeypatch, payloads[vision.MODEL_FILENAME])
    urls = []

    def opener(request, timeout=45):
        urls.append(request.full_url)
        name = request.full_url.rsplit("/", 1)[-1]
        return Response(payloads[name])

    events = []
    path = vision.install_model(tmp_path / "model", opener=opener, progress=events.append, chunk_size=2)

    assert vision.model_ready(path)
    assert (path / vision.MODEL_FILENAME).read_bytes() == payloads[vision.MODEL_FILENAME]
    assert len(urls) == len(vision.MODEL_FILES)
    assert all(vision.MODEL_REVISION in url for url in urls)
    assert all(not url.endswith((".bin", ".py")) for url in urls)
    assert events and any(event.file_fraction == 1 for event in events)


def test_cancel_keeps_partial_file_and_retry_resumes(tmp_path, monkeypatch):
    payloads = {name: (b"model-weight-bytes" if name == vision.MODEL_FILENAME else name.encode()) for name in vision.MODEL_FILES}
    prepare_expected_hash(monkeypatch, payloads[vision.MODEL_FILENAME])
    folder = tmp_path / "model"
    token = Token()
    requests = []

    def first_opener(request, timeout=45):
        filename = request.full_url.rsplit("/", 1)[-1]
        requests.append((filename, request.get_header("Range")))
        return Response(payloads[filename])

    def cancel_after_first_chunk(event):
        if event.filename == vision.MODEL_FILES[0] and event.file_bytes >= 3:
            token.cancelled = True

    with pytest.raises(vision.DownloadCancelled):
        vision.install_model(folder, opener=first_opener, progress=cancel_after_first_chunk, cancel=token, chunk_size=3)
    partial = folder / (vision.MODEL_FILES[0] + ".part")
    assert partial.exists() and partial.stat().st_size >= 3

    token.cancelled = False
    requests.clear()

    def resume_opener(request, timeout=45):
        filename = request.full_url.rsplit("/", 1)[-1]
        range_value = request.get_header("Range")
        requests.append((filename, range_value))
        start = int(range_value.split("=", 1)[1].split("-", 1)[0]) if range_value else 0
        return Response(payloads[filename], 206 if range_value else 200, start)

    installed = vision.install_model(folder, opener=resume_opener, cancel=token, chunk_size=4)
    assert vision.model_ready(installed)
    assert requests[0][1] is not None


def test_bad_weight_digest_is_discarded(tmp_path, monkeypatch):
    payloads = {name: name.encode() for name in vision.MODEL_FILES}
    monkeypatch.setattr(vision, "MODEL_SHA256", "0" * 64)

    def opener(request, timeout=45):
        return Response(payloads[request.full_url.rsplit("/", 1)[-1]])

    with pytest.raises(vision.VisionAssistError, match="SHA-256"):
        vision.install_model(tmp_path / "model", opener=opener)
    assert not (tmp_path / "model" / vision.MODEL_FILENAME).exists()
    assert not (tmp_path / "model" / (vision.MODEL_FILENAME + ".part")).exists()


def test_ocr_quadrilaterals_are_clipped_and_normalized():
    candidates = vision.parse_ocr_regions(
        {"labels": ["Name", "outside", "bad"], "quad_boxes": [[10, 20, 50, 20, 50, 40, 10, 40], [-4, 2, 120, 2, 120, 60, -4, 60], [1, 2]]},
        width=100,
        height=50,
    )
    assert candidates[0].text == "Name"
    assert candidates[0].rect == (.1, .4, .5, .8)
    assert candidates[1].rect == (0, .04, 1, 1)
    assert candidates[0].confidence is None


def test_analyze_page_only_returns_review_evidence_and_needs_installed_model(tmp_path):
    image = type("Image", (), {"size": (100, 80), "convert": lambda self, mode: self})()
    with pytest.raises(vision.VisionAssistError, match="not installed"):
        vision.analyze_page(image, tmp_path / "missing")

    for name in vision.MODEL_FILES:
        (tmp_path / name).write_bytes(b"present")

    class Processor:
        def __call__(self, **kwargs):
            return {"image": kwargs["images"]}

        def batch_decode(self, generated, **kwargs):
            return ["ocr result"]

        def post_process_generation(self, text, task, image_size):
            return {task: {"labels": ["Parent name"], "quad_boxes": [[5, 10, 45, 10, 45, 20, 5, 20]]}}

    class Model:
        def generate(self, **kwargs):
            return ["mock"]

    result = vision.analyze_page(image, tmp_path, model=Model(), processor=Processor())
    assert result.width == 100 and result.height == 80
    assert result.raw_text == "ocr result"
    assert result.candidates[0].text == "Parent name"
    assert result.candidates[0].rect == (.05, .125, .45, .25)

