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
        assert bridge.setField(first.key,json.dumps({"value":"Copied through the chain"}))=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==["Copied through the chain"]*3
        assert bridge.undo()=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==[""]*3
        assert bridge.redo()=="ok"
        assert [next(item.value for item in bridge.document.fields if item.key==key) for key in (first.key,middle.key,last.key)]==["Copied through the chain"]*3

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
