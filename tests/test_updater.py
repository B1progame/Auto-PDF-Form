import hashlib
import io
import json
import threading

import pytest

import updater


class Response:
    def __init__(self, body):
        self.body = body
        self.headers = {"Content-Length": str(len(body))}
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.body)
        result = self.body[self.offset:self.offset + size]
        self.offset += len(result)
        return result


def _release(installer_bytes):
    name = "AutoPDFForm-Setup-1.2.0.exe"
    digest = hashlib.sha256(installer_bytes).hexdigest()
    return {
        "tag_name": "v1.2.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/B1progame/Auto-PDF-Form/releases/tag/v1.2.0",
        "body": "New features",
        "assets": [
            {"name": name, "size": len(installer_bytes), "digest": f"sha256:{digest}",
             "browser_download_url": f"https://github.com/B1progame/Auto-PDF-Form/releases/download/v1.2.0/{name}"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/B1progame/Auto-PDF-Form/releases/download/v1.2.0/SHA256SUMS.txt"},
        ],
    }


def test_version_order_handles_release_candidates():
    assert updater.version_key("v1.2.0") > updater.version_key("1.2.0-rc.1")
    assert updater.version_key("1.2.0") > updater.version_key("1.1.99")
    with pytest.raises(updater.UpdateError, match="Unsupported"):
        updater.version_key("latest")


def test_check_latest_finds_stable_setup_and_ignores_old_release():
    release = _release(b"setup")
    request_urls = []

    def opener(request, timeout):
        request_urls.append(request.full_url)
        return Response(json.dumps(release).encode())

    result = updater.check_latest("1.1.0", opener=opener)
    assert result["available"] is True
    assert result["latestVersion"] == "1.2.0"
    assert result["installer"]["name"] == "AutoPDFForm-Setup-1.2.0.exe"
    assert request_urls == [updater.API_URL]
    assert updater.check_latest("1.2.0", opener=opener)["available"] is False


def test_download_verifies_manifest_digest_then_atomically_publishes(tmp_path):
    data = b"verified setup payload"
    release = updater.check_latest("1.1.0", opener=lambda *_args, **_kwargs: Response(json.dumps(_release(data)).encode()))
    expected_line = f"{hashlib.sha256(data).hexdigest()}  {release['installer']['name']}\n".encode()
    events = []

    def opener(request, timeout):
        if request.full_url.endswith("SHA256SUMS.txt"):
            return Response(expected_line)
        return Response(data)

    target = tmp_path / "AutoPDFForm-Setup-1.2.0.exe"
    saved = updater.download_installer(release, target, opener=opener, chunk_size=4, progress=lambda got, total: events.append((got, total)))
    assert saved == target
    assert saved.read_bytes() == data
    assert not target.with_name(target.name + ".part").exists()
    assert events[-1] == (len(data), len(data))


def test_download_refuses_checksum_mismatch_and_leaves_no_installer(tmp_path):
    data = b"tampered installer"
    release = updater.check_latest("1.1.0", opener=lambda *_args, **_kwargs: Response(json.dumps(_release(data)).encode()))
    bad_line = f"{'0' * 64}  {release['installer']['name']}\n".encode()
    target = tmp_path / "setup.exe"

    def opener(request, timeout):
        if request.full_url.endswith("SHA256SUMS.txt"):
            return Response(bad_line)
        return Response(data)

    with pytest.raises(updater.UpdateError, match="does not match"):
        updater.download_installer(release, target, opener=opener)
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_cancel_download_does_not_publish_partial_file(tmp_path):
    data = b"installer"
    release = updater.check_latest("1.1.0", opener=lambda *_args, **_kwargs: Response(json.dumps(_release(data)).encode()))
    sums = f"{hashlib.sha256(data).hexdigest()}  {release['installer']['name']}\n".encode()
    cancel = threading.Event()

    def opener(request, timeout):
        return Response(sums if request.full_url.endswith("SHA256SUMS.txt") else data)

    cancel.set()
    target = tmp_path / "setup.exe"
    with pytest.raises(updater.UpdateCancelled):
        updater.download_installer(release, target, opener=opener, cancel=cancel)
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()

