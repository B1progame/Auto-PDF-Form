from pathlib import Path
import sys
import tempfile
import time
import copy
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QMimeData,QUrl
from PySide6.QtGui import QDropEvent,QDragEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import Studio,FieldItem
from engine import export_pdf,load_document
from test_engine import source


def wait_until(predicate,timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        QApplication.processEvents();QTest.qWait(25)
        if predicate():return
    raise AssertionError('UI operation timed out')


@pytest.fixture(scope='session')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,source,tmp_path,monkeypatch):
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))
    win=Studio();errors=[];win.error=lambda text:errors.append(text);win.show();QTest.qWait(80)
    win.open_path(str(source));wait_until(lambda:win.document is not None and not win.busy)
    win.auto_detect();wait_until(lambda:bool(win.document.fields) and not win.busy and any(isinstance(i,FieldItem) for i in win.scene.items()))
    yield win
    win.force_close=True;win.close();QApplication.processEvents()
    assert not errors,errors


def select_text(win):
    spec=next(f for f in win.document.fields if f.kind=='text' and not f.max_length)
    item=next(i for i in win.scene.items() if isinstance(i,FieldItem) and i.spec.key==spec.key)
    item.setSelected(True);QApplication.processEvents();return spec,item


def test_inspector_edit_undo_redo_export(window,tmp_path):
    win=window;spec,item=select_text(win);key=spec.key;before=spec.rect.copy()
    win.geometry['X'].setValue(before[0]+8);win.geometry['Width'].setValue(before[2]-before[0]+15)
    win.font_size.setValue(16);win.max_chars.setValue(30);win.value_edit.setPlainText('Editor test')
    win.color_buttons['text_color'].setProperty('color','#7044bb');win.color_buttons['highlight'].setProperty('color','#bb88ff');win.commit_inspector()
    changed=next(f for f in win.document.fields if f.key==key)
    assert changed.rect[0]==pytest.approx(before[0]+8,abs=.01) and changed.font_size==16 and changed.highlight=='#bb88ff'
    win.undo();assert next(f for f in win.document.fields if f.key==key).rect==before
    win.redo();assert next(f for f in win.document.fields if f.key==key).value=='Editor test'
    out=tmp_path/'edited.pdf';export_pdf(win.document,out)
    loaded=next(f for f in load_document(out).fields if f.name==changed.name)
    assert loaded.font_size==16 and loaded.value=='Editor test' and loaded.rect==pytest.approx(changed.rect)
    Path('validation').mkdir(exist_ok=True);win.grab().save('validation/editor-test.png')


def test_mouse_drag_and_corner_resize(window):
    win=window;spec,item=select_text(win);key=spec.key;before=spec.rect.copy()
    win.view.ensureVisible(item);QTest.qWait(80)
    center=win.view.mapFromScene(item.mapToScene(item.box.center()))
    QTest.mousePress(win.view.viewport(),Qt.LeftButton,Qt.NoModifier,center)
    QTest.mouseMove(win.view.viewport(),center+QPoint(25,12),80)
    QTest.mouseRelease(win.view.viewport(),Qt.LeftButton,Qt.NoModifier,center+QPoint(25,12))
    wait_until(lambda:next(f for f in win.document.fields if f.key==key).rect!=before)
    wait_until(lambda:any(isinstance(i,FieldItem) and i.spec.key==key for i in win.scene.items()))
    moved=next(f for f in win.document.fields if f.key==key).rect.copy()
    item=next(i for i in win.scene.items() if isinstance(i,FieldItem) and i.spec.key==key);item.setSelected(True);win.view.ensureVisible(item);QTest.qWait(80)
    corner=win.view.mapFromScene(item.mapToScene(item.box.bottomRight()))
    QTest.mousePress(win.view.viewport(),Qt.LeftButton,Qt.NoModifier,corner)
    QTest.mouseMove(win.view.viewport(),corner+QPoint(22,14),80)
    QTest.mouseRelease(win.view.viewport(),Qt.LeftButton,Qt.NoModifier,corner+QPoint(22,14))
    wait_until(lambda:next(f for f in win.document.fields if f.key==key).rect[2]-next(f for f in win.document.fields if f.key==key).rect[0]>moved[2]-moved[0]+3)


def test_radio_exclusion_and_sample_preview(window):
    win=window;options=[f for f in win.document.fields if f.kind=='radio'];assert len(options)==2
    win.toggle_checked(options[0].key);win.toggle_checked(options[1].key)
    assert sum(f.checked for f in win.document.fields if f.kind=='radio')==1
    before=copy.deepcopy(win.document.fields);win.toggle_preview()
    wait_until(lambda:win.preview_path is not None and not win.busy)
    assert win.document.fields==before
    win.toggle_preview();assert win.preview_path is None


def test_field_search_and_category_filter(window):
    win=window
    win.field_type.setCurrentText('Text')
    visible=[win.field_list.item(i).data(Qt.UserRole) for i in range(win.field_list.count())]
    assert visible and all(next(f for f in win.document.fields if f.key==key).kind=='text' for key in visible)
    win.field_type.setCurrentText('All types')
    win.field_search.setText('day')
    matches=[win.field_list.item(i).data(Qt.UserRole) for i in range(win.field_list.count())]
    assert matches and all('day' in next(f for f in win.document.fields if f.key==key).name.casefold() for key in matches)
    assert ' / ' in win.fields_label.text()


def test_dragging_pdf_onto_window_opens_it(app,source,tmp_path,monkeypatch):
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))
    win=Studio();win.error=lambda text:pytest.fail(text);win.show();QTest.qWait(50)
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(source))])
    enter=QDragEnterEvent(QPoint(100,100),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    win.dragEnterEvent(enter);assert enter.isAccepted()
    drop=QDropEvent(QPointF(100,100),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    win.dropEvent(drop)
    wait_until(lambda:win.document is not None and not win.busy)
    assert Path(win.document.source)==Path(source)
    win.force_close=True;win.close();QApplication.processEvents()
