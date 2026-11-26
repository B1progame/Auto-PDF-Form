import json
import sys
import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Field, load_document
from web_editor import Bridge
import updater
from test_engine import source


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError("web editor operation timed out")


def test_web_bridge_stages_choices_exclusively_and_exports(app, source, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    bridge = Bridge()
    errors = []
    bridge.event.connect(lambda raw: errors.append(json.loads(raw)) if json.loads(raw).get("type") == "error" else None)
    try:
        assert bridge.open_path(str(source))
        wait_until(app, lambda: bridge.document is not None and not bridge.busy)

        assert bridge.autoAnalyze(json.dumps({"discover": True, "scope": "page"})) == "queued"
        wait_until(app, lambda: bridge.pending is not None and not bridge.busy)
        assert bridge.document.fields == []  # suggestions remain staged until review
        assert bridge.pending[1]["scope_pages"] == [1]
        assert bridge.applyAutomatic() == "ok"

        radios = [field for field in bridge.document.fields if field.kind == "radio"]
        assert len(radios) == 2
        assert bridge.setField(radios[0].key, json.dumps({"checked": True})) == "ok"
        assert bridge.setField(radios[1].key, json.dumps({"checked": True})) == "ok"
        assert [field.checked for field in bridge.document.fields if field.group == radios[0].group] == [False, True]

        first=Field.make("linked_first",0,[20,300,200,324])
        middle=Field.make("linked_middle",0,[20,260,200,284])
        last=Field.make("linked_last",0,[20,220,200,244])
        first.linked_fields=[middle.key]
        middle.linked_fields=[last.key]
        bridge.document.fields.extend([first,middle,last])
        first.link_rules={middle.key:{"transform":"uppercase","condition":"source_non_empty"}}
        middle.link_rules={last.key:{"transform":"trim","condition":"always"}}
        linked_value="  Copied through the chain  "
        transformed_values=[linked_value,"  COPIED THROUGH THE CHAIN  ","COPIED THROUGH THE CHAIN"]
        assert bridge.setField(first.key,json.dumps({"value":linked_value}))=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==transformed_values
        assert bridge.undo()=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==[""]*3
        assert bridge.redo()=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==transformed_values

        rewrite_key=bridge.addRewrite()
        assert rewrite_key not in {"unavailable",""}
        assert bridge.setRewrite(rewrite_key,json.dumps({"rect":[55,685,240,715],"text":"Visible correction","font":"Times-Roman"}))=="ok"

        output = tmp_path / "browser-bridge-export.pdf"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), "PDF (*.pdf)"))
        assert bridge.exportPDF() == "queued"
        wait_until(app, lambda: not bridge.busy and output.is_file())
        reopened = load_document(output)
        assert len(reopened.fields) == len(bridge.document.fields)
        assert sum(field.checked for field in reopened.fields if field.group == radios[0].group) == 1
        assert "Visible correction" in __import__("pypdf").PdfReader(output).pages[0].extract_text()
        assert not errors, errors
    finally:
        bridge.shutdown()


def test_update_check_and_verified_download_are_asynchronous_and_report_progress(app, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(updater, "default_update_dir", lambda: tmp_path)
    release = {
        "currentVersion": "1.1.0", "latestVersion": "1.2.0", "available": True,
        "releaseUrl": "https://github.com/B1progame/Auto-PDF-Form/releases/tag/v1.2.0",
        "releaseNotes": "A tested update", "publishedAt": "2026-10-28T00:00:00Z",
        "installer": {"name": "AutoPDFForm-Setup-1.2.0.exe", "size": 3}, "checksums": {},
    }
    monkeypatch.setattr(updater, "check_latest", lambda version: release)
    bridge = Bridge()
    events = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    try:
        assert bridge.checkForUpdates() == "queued"
        wait_until(app, lambda: any(event.get("status") == "available" for event in events) and not bridge.update_task_active)
        assert bridge.update_release is release

        def fake_download(update, destination, *, progress, cancel):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"ok!")
            progress(1, 3)
            progress(3, 3)
            return destination

        monkeypatch.setattr(updater, "download_installer", fake_download)
        assert bridge.downloadUpdate() == "queued"
        wait_until(app, lambda: any(event.get("status") == "downloaded" for event in events) and not bridge.update_task_active)
        assert bridge.update_installer.read_bytes() == b"ok!"
        assert any(event.get("status") == "downloading" and event.get("progress") == 100 for event in events)
    finally:
        bridge.shutdown()
