"""PySide desktop host and narrow local bridge for the Vite/React editor."""
from __future__ import annotations

import base64
import copy
import json
import re
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QFileDialog, QMessageBox
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

import engine
from engine import Document, Field, Rewrite


class WorkerSignals(QObject):
    result = Signal(str, object)
    error = Signal(str, str)
    finished = Signal(str)


class Worker(QRunnable):
    def __init__(self, request_id: str, fn):
        super().__init__()
        self.request_id = request_id
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.request_id, self.fn())
        except Exception as exc:  # surfaced to the React status/toast area
            self.signals.error.emit(self.request_id, str(exc))
        finally:
            self.signals.finished.emit(self.request_id)


class Bridge(QObject):
    """Only exposes document operations required by the bundled local UI."""

    event = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document: Document | None = None
        self.page = 0
        self.project_path: str | None = None
        self.preview_path: str | None = None
        self.pending: tuple[Document, dict] | None = None
        self.report: dict | None = None
        self.dirty = False
        self.busy = False
        self.history: list[tuple[list[Field], list[Rewrite]]] = []
        self.redo_history: list[tuple[list[Field], list[Rewrite]]] = []
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.temp = tempfile.TemporaryDirectory(prefix="PDFFormStudioWeb_")
        self.callbacks = {}
        self.running = {}
        self.images: dict[tuple[str, int, bool], str] = {}
        self.render_tokens: dict[str, str] = {}

    def _emit(self, kind: str, **payload):
        self.event.emit(json.dumps({"type": kind, **payload}, ensure_ascii=False))

    def _fields(self):
        return [asdict(f) for f in self.document.fields] if self.document else []

    def state(self):
        doc = self.document
        return {
            "source": doc.source if doc else "",
            "filename": Path(doc.source).name if doc else "",
            "page": self.page,
            "pages": [
                {"index": i, "width": size[0], "height": size[1],
                 "fields": sum(f.page == i for f in doc.fields)}
                for i, size in enumerate(doc.sizes)
            ] if doc else [],
            "fields": self._fields(),
            "rewrites": [asdict(r) for r in doc.rewrites] if doc else [],
            "unsupported": list(doc.unsupported) if doc else [],
            "warnings": list(doc.warnings) if doc else [],
            "dirty": self.dirty,
            "busy": self.busy,
            "preview": bool(self.preview_path),
            "report": self.report,
            "pending": self.pending[1] if self.pending else None,
            "canUndo": bool(self.history),
            "canRedo": bool(self.redo_history),
            "projectPath": self.project_path,
        }

    def _emit_state(self):
        self._emit("state", state=self.state())

    def _start(self, request_id, fn, callback, *, blocks_ui=True):
        if blocks_ui and self.busy:
            return False
        if blocks_ui:
            self.busy = True
            self._emit_state()
        self.callbacks[request_id] = (callback, blocks_ui)
        worker = Worker(request_id, fn)
        worker.signals.result.connect(self._completed)
        worker.signals.error.connect(self._failed)
        worker.signals.finished.connect(self._finished)
        self.running[request_id] = worker
        self.pool.start(worker)
        return True

    @Slot(str, object)
    def _completed(self, request_id, result):
        entry = self.callbacks.get(request_id)
        if entry:
            entry[0](result)

    @Slot(str, str)
    def _failed(self, request_id, message):
        self._emit("error", message=message, requestId=request_id)

    @Slot(str)
    def _finished(self, request_id):
        entry = self.callbacks.pop(request_id, None)
        self.running.pop(request_id, None)
        if entry and entry[1]:
            self.busy = False
        self._emit_state()

    @Slot(result=str)
    def getState(self):
        return json.dumps(self.state(), ensure_ascii=False)

    def open_path(self, path):
        if self.busy:
            return False
        path = str(Path(path).resolve())
        if self.dirty and self.document:
            answer = QMessageBox.question(
                None, "Unsaved project", "Discard unsaved changes and open another file?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if answer != QMessageBox.Discard:
                return False
        self.preview_path = None
        request_id = uuid.uuid4().hex

        def loaded(doc):
            self.document = doc
            self.page = 0
            self.project_path = path if path.lower().endswith(".json") else None
            self.history.clear()
            self.redo_history.clear()
            self.report = None
            self.pending = None
            self.images.clear()
            self.dirty = False
            self._emit_state()
            self.requestPage(0, "open")
            for i in range(min(12, len(doc.sizes))):
                self.requestThumbnail(i)
            if doc.unsupported:
                self._emit("warning", message="This PDF can be viewed, but editing/export is blocked:")

        fn = (lambda: engine.load_project(path)) if path.lower().endswith(".json") else (lambda: engine.load_document(path))
        return self._start(request_id, fn, loaded)

    @Slot(result=str)
    def openDialog(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Open PDF or Form Studio project", "",
            "PDF or project (*.pdf *.formstudio.json);;PDF (*.pdf);;Project (*.formstudio.json)",
        )
        if path:
            self.open_path(path)
        return "opened" if path else "cancelled"

    @Slot(str, result=str)
    def openPath(self, path):
        return "opened" if self.open_path(path) else "cancelled"

    @Slot(int, result=str)
    def setPage(self, page):
        if not self.document or not 0 <= page < len(self.document.sizes):
            return "invalid page"
        self.page = page
        self._emit_state()
        self.requestPage(page, "navigation")
        return "ok"

    def _render(self, page, preview):
        path = self.preview_path if preview and self.preview_path else self.document.source
        key = (path, page, bool(preview and self.preview_path))
        if key in self.images:
            return self.images[key]
        image = engine.render_page(path, page, 1.35 if not preview else 1.15, bool(preview and self.preview_path))
        from io import BytesIO
        data = BytesIO()
        image.save(data, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")

    @Slot(int, str, result=str)
    def requestPage(self, page, reason="navigation"):
        if not self.document or not 0 <= page < len(self.document.sizes):
            return "invalid page"
        request_id = uuid.uuid4().hex
        self.render_tokens[reason] = request_id
        key = (self.preview_path if self.preview_path else self.document.source, page, bool(self.preview_path))
        if key in self.images:
            self._emit("page", page=page, image=self.images[key], reason=reason, requestId=request_id)
            return "cached"

        def ready(data):
            if self.render_tokens.get(reason) != request_id:
                return
            self.images[key] = data
            self._emit("page", page=page, image=data, reason=reason, requestId=request_id)

        self._start(request_id, lambda: self._render(page, bool(self.preview_path)), ready, blocks_ui=False)
        return "queued"

    @Slot(int, result=str)
    def requestThumbnail(self, page):
        if not self.document or not 0 <= page < len(self.document.sizes):
            return "invalid page"
        request_id = uuid.uuid4().hex
        path = self.document.source

        def render():
            from io import BytesIO
            image = engine.render_page(path, page, .28, False)
            data = BytesIO(); image.save(data, format="PNG", optimize=True)
            return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")

        def ready(data):
            self._emit("thumbnail", page=page, image=data)

        self._start(request_id, render, ready, blocks_ui=False)
        return "queued"

    def _snapshot(self):
        return copy.deepcopy((self.document.fields, self.document.rewrites))

    def _restore(self, snapshot):
        self.document.fields, self.document.rewrites = copy.deepcopy(snapshot)

    def _commit(self, before):
        self.history.append(before)
        self.history = self.history[-100:]
        self.redo_history.clear()
        self.dirty = True
        self.pending = None
        self.images.clear()
        self._emit_state()
        self.requestPage(self.page, "edit")

    @Slot(str, str, result=str)
    def setField(self, key, patch_json):
        if not self.document or self.busy or self.preview_path:
            return "unavailable"
        target = next((f for f in self.document.fields if f.key == key), None)
        if target is None:
            return "field not found"
        before = None
        try:
            patch = json.loads(patch_json)
            allowed = {
                "name", "tooltip", "rect", "value", "font_size", "font", "text_color",
                "background", "border_color", "border_width", "highlight", "multiline",
                "max_length", "group", "option", "checked", "choices", "alignment",
                "locked", "linked_fields",
            }
            if not isinstance(patch, dict) or not set(patch).issubset(allowed):
                raise ValueError("Invalid field update")
            before = self._snapshot()
            for prop, value in patch.items():
                if prop == "rect":
                    if not isinstance(value, list) or len(value) != 4:
                        raise ValueError("Position must have four numbers")
                    pw, ph = self.document.sizes[target.page]
                    x0,y0,x1,y1 = map(float, value)
                    width=max(3,min(pw,x1-x0)); height=max(3,min(ph,y1-y0))
                    x0=max(0,min(pw-width,x0)); y0=max(0,min(ph-height,y0))
                    value=[x0,y0,x0+width,y0+height]
                if prop in {"text_color", "background", "border_color", "highlight"}:
                    if value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)):
                        raise ValueError(f"Invalid {prop.replace('_',' ')} color")
                if prop in {"font_size", "border_width", "max_length", "alignment"}:
                    value = float(value) if prop in {"font_size", "border_width"} else int(value)
                if prop == "linked_fields":
                    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                        raise ValueError("Linked field list is invalid.")
                    value = list(dict.fromkeys(value))
                setattr(target, prop, value)
            if target.kind == "radio":
                if not target.group.strip():
                    target.group = target.name
                target.name = target.group
                if target.checked:
                    for field in self.document.fields:
                        if field.kind == "radio" and field.group == target.group and field.key != target.key:
                            field.checked = False
            if target.kind == "choice":
                target.choices = [str(v) for v in target.choices if str(v).strip()]
            if "value" in patch:
                by_key = {field.key: field for field in self.document.fields}
                queue = [target]
                visited = {target.key}
                while queue:
                    source = queue.pop(0)
                    for linked_key in source.linked_fields:
                        linked = by_key.get(linked_key)
                        if linked is None or linked.kind not in {"text", "choice"}:
                            raise ValueError("A linked target must be another text field or dropdown.")
                        if linked.key in visited:
                            continue
                        linked.value = source.value
                        visited.add(linked.key)
                        queue.append(linked)
            engine.validate_document(self.document)
            if before == self._snapshot():
                return "unchanged"
            self._commit(before)
            return "ok"
        except Exception as exc:
            if before is not None:
                self._restore(before)
            self._emit("error", message=str(exc))
            self._emit_state()
            return str(exc)

    @Slot(str, result=str)
    def addField(self, kind):
        if not self.document or self.busy or self.preview_path:
            return "unavailable"
        if kind not in {"text", "checkbox", "radio", "choice"}:
            return "unsupported field type"
        count = len(self.document.fields) + 1
        pw, ph = self.document.sizes[self.page]
        width, height = (190, 28) if kind in {"text", "choice"} else (16, 16)
        x0 = max(8, min((pw-width)/2, 72))
        y0 = max(8, min(ph-160, ph*.65))
        group = f"choice_{count}"
        f = Field.make(f"field_{count}", self.page, [x0,y0,x0+width,y0+height], kind=kind,
                       group=group if kind=="radio" else "", option="Option 1" if kind=="radio" else "Yes",
                       border_width=.7, multiline=(kind=="text" and height>32))
        before=self._snapshot()
        self.document.fields.append(f)
        self._commit(before)
        self._emit("selectField", key=f.key)
        return f.key

    @Slot(result=str)
    def addRewrite(self):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        width,height=self.document.sizes[self.page]
        box_width=max(3,min(252,width-16));box_height=max(3,min(36,height-16))
        x0=(width-box_width)/2;y0=max(8,min(height-box_height-8,height-144-box_height))
        rect=[x0,y0,x0+box_width,y0+box_height]
        rewrite=Rewrite.make(self.page,rect,text="Replacement text")
        before=self._snapshot();self.document.rewrites.append(rewrite);self._commit(before)
        self._emit("selectRewrite",key=rewrite.key)
        return rewrite.key

    @Slot(str, str, result=str)
    def setRewrite(self, key, patch_json):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        rewrite=next((item for item in self.document.rewrites if item.key==key),None)
        if rewrite is None:return "rewrite not found"
        before=None
        try:
            patch=json.loads(patch_json);allowed={"text","rect","font_size","font","text_color","fill"}
            if not isinstance(patch,dict) or not set(patch).issubset(allowed):raise ValueError("Invalid text correction update.")
            before=self._snapshot()
            for prop,value in patch.items():
                if prop=="rect":self._apply_rewrite_rect(rewrite,value)
                elif prop in {"text_color","fill"} and (not isinstance(value,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",value)):
                    raise ValueError("Correction colors must be six-digit hex colors.")
                elif prop=="font_size":value=float(value)
                elif prop=="font" and value not in {"Helvetica","Times-Roman","Courier"}:raise ValueError("Unsupported correction font.")
                setattr(rewrite,prop,value)
            engine.validate_document(self.document)
            if before==self._snapshot():return "unchanged"
            self._commit(before);return "ok"
        except Exception as exc:
            if before is not None:self._restore(before)
            self._emit("error",message=str(exc));self._emit_state();return str(exc)

    def _apply_rect(self, field, rect):
        if field.locked:
            return False
        pw, ph = self.document.sizes[field.page]
        x0, y0, x1, y1 = map(float, rect)
        width=max(3,min(pw,x1-x0));height=max(3,min(ph,y1-y0))
        x0=max(0,min(pw-width,x0));y0=max(0,min(ph-height,y0))
        field.rect=[x0,y0,x0+width,y0+height]
        return True

    def _apply_rewrite_rect(self, rewrite, rect):
        pw,ph=self.document.sizes[rewrite.page]
        x0,y0,x1,y1=map(float,rect);width=max(3,min(pw,x1-x0));height=max(3,min(ph,y1-y0))
        x0=max(0,min(pw-width,x0));y0=max(0,min(ph-height,y0))
        rewrite.rect=[x0,y0,x0+width,y0+height]

    @Slot(str, result=str)
    def setFieldBatch(self, patches_json):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        before=None
        try:
            patches=json.loads(patches_json)
            before=self._snapshot()
            for patch in patches:
                target=next((f for f in self.document.fields if f.key==patch.get("key")),None)
                if target and "rect" in patch:self._apply_rect(target,patch["rect"])
                rewrite=next((r for r in self.document.rewrites if r.key==patch.get("key")),None)
                if rewrite and "rect" in patch:self._apply_rewrite_rect(rewrite,patch["rect"])
            engine.validate_document(self.document)
            if before==self._snapshot():return "unchanged"
            self._commit(before);return "ok"
        except Exception as exc:
            if before is not None:self._restore(before)
            self._emit("error",message=str(exc));self._emit_state();return str(exc)

    @Slot(str, float, float, result=str)
    def moveFields(self, keys_json, dx, dy):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        keys=set(json.loads(keys_json));before=self._snapshot()
        for field in self.document.fields:
            if field.key in keys and not field.locked:
                x0,y0,x1,y1=field.rect
                self._apply_rect(field,[x0+dx,y0+dy,x1+dx,y1+dy])
        for rewrite in self.document.rewrites:
            if rewrite.key in keys:
                x0,y0,x1,y1=rewrite.rect
                self._apply_rewrite_rect(rewrite,[x0+dx,y0+dy,x1+dx,y1+dy])
        if before==self._snapshot():return "unchanged"
        self._commit(before);return "ok"

    @Slot(str, str, result=str)
    def alignFields(self, keys_json, mode):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        selected=[f for f in self.document.fields if f.key in set(json.loads(keys_json)) and not f.locked]
        if len(selected)<2:return "select at least two unlocked fields"
        before=self._snapshot();rects=[f.rect[:] for f in selected]
        x0=min(r[0] for r in rects);y0=min(r[1] for r in rects);x1=max(r[2] for r in rects);y1=max(r[3] for r in rects)
        if mode=="left":new=[[x0,r[1],x0+r[2]-r[0],r[3]] for r in rects]
        elif mode=="right":new=[[x1-(r[2]-r[0]),r[1],x1,r[3]] for r in rects]
        elif mode=="center":new=[[((x0+x1)-(r[2]-r[0]))/2,r[1],((x0+x1)+(r[2]-r[0]))/2,r[3]] for r in rects]
        elif mode=="top":new=[[r[0],y1-(r[3]-r[1]),r[2],y1] for r in rects]
        elif mode=="bottom":new=[[r[0],y0,r[2],y0+(r[3]-r[1])] for r in rects]
        elif mode=="distribute" and len(rects)>=3:
            ordered=sorted(range(len(rects)),key=lambda i:rects[i][0]);total=sum(rects[i][2]-rects[i][0] for i in ordered);gap=(x1-x0-total)/(len(rects)-1);cursor=x0;new=[r[:] for r in rects]
            for i in ordered:
                width=rects[i][2]-rects[i][0];new[i]=[cursor,rects[i][1],cursor+width,rects[i][3]];cursor+=width+gap
        else:return "invalid alignment"
        for field,rect in zip(selected,new):self._apply_rect(field,rect)
        engine.validate_document(self.document)
        if before==self._snapshot():return "unchanged"
        self._commit(before);return "ok"

    @Slot(str, result=str)
    def duplicateField(self, key):
        if not self.document or self.busy or self.preview_path:
            return "unavailable"
        source=next((f for f in self.document.fields if f.key==key),None)
        if not source:return "field not found"
        before=self._snapshot()
        new=copy.deepcopy(source);new.key=uuid.uuid4().hex;new.name=source.name+"_copy";new.value="";new.checked=False;new.linked_fields=[]
        dx=10;dy=-10;pw,ph=self.document.sizes[source.page];w=new.rect[2]-new.rect[0];h=new.rect[3]-new.rect[1]
        x=max(0,min(pw-w,new.rect[0]+dx));y=max(0,min(ph-h,new.rect[1]+dy));new.rect=[x,y,x+w,y+h]
        if new.kind=="radio":
            new.group=source.group;new.name=source.group
            used={f.option for f in self.document.fields if f.kind=="radio" and f.group==new.group}
            n=1
            while f"Option {n}" in used:n+=1
            new.option=f"Option {n}"
        else:
            names={f.name for f in self.document.fields}
            n=1
            while f"{source.name}_copy{n}" in names:n+=1
            new.name=f"{source.name}_copy{n}"
        self.document.fields.append(new);self._commit(before);self._emit("selectField",key=new.key);return new.key

    @Slot(str, result=str)
    def deleteFields(self, keys_json):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        keys=set(json.loads(keys_json));before=self._snapshot()
        self.document.fields=[f for f in self.document.fields if f.key not in keys]
        self.document.rewrites=[r for r in self.document.rewrites if r.key not in keys]
        for field in self.document.fields:
            field.linked_fields=[key for key in field.linked_fields if key not in keys]
        if before==self._snapshot():return "unchanged"
        self._commit(before);return "ok"

    @Slot(result=str)
    def undo(self):
        if not self.history or self.busy or self.preview_path:return "unavailable"
        self.redo_history.append(self._snapshot());self._restore(self.history.pop());self.dirty=True;self.images.clear();self._emit_state();self.requestPage(self.page,"undo");return "ok"

    @Slot(result=str)
    def redo(self):
        if not self.redo_history or self.busy or self.preview_path:return "unavailable"
        self.history.append(self._snapshot());self._restore(self.redo_history.pop());self.dirty=True;self.images.clear();self._emit_state();self.requestPage(self.page,"redo");return "ok"

    @Slot(str, result=str)
    def autoAnalyze(self, options_json):
        if not self.document or self.busy or self.preview_path:return "unavailable"
        options=json.loads(options_json or "{}")
        snapshot=copy.deepcopy(self.document)
        discover=bool(options.get("discover",not bool(snapshot.fields)))
        page=self.page if options.get("scope")=="page" else None
        request_id=uuid.uuid4().hex
        def analyzed(result):
            staged,report=result
            self.pending=(staged,report)
            self._emit("analysis",report=report,fields=[asdict(f) for f in staged.fields])
            self._emit_state()
        self._start(request_id,lambda:engine.analyze(snapshot,discover=discover,pages=None if page is None else {page}),analyzed)
        return "queued"

    @Slot(result=str)
    def applyAutomatic(self):
        if not self.pending or not self.document:return "nothing to apply"
        staged,report=self.pending;before=self._snapshot()
        self.document.fields=copy.deepcopy(staged.fields);self.report=copy.deepcopy(report);self.history.append(before);self.history=self.history[-100:];self.redo_history.clear();self.dirty=True;self.pending=None;self.images.clear();self._emit_state();self.requestPage(self.page,"analysis");return "ok"

    @Slot(result=str)
    def discardAutomatic(self):
        self.pending=None;self._emit_state();return "ok"

    @Slot(result=str)
    def templateDialog(self):
        if not self.document or self.busy:return "unavailable"
        path,_=QFileDialog.getOpenFileName(None,"Choose a matching fillable PDF template","","PDF (*.pdf)")
        if not path:return "cancelled"
        request_id=uuid.uuid4().hex
        def ready(doc):
            before=self._snapshot();self.document.fields=doc.fields;self._commit(before);self._emit("notice",message=f"Transferred {len(doc.fields)} fields after checking every page against the source artwork.")
        self._start(request_id,lambda:engine.transfer_template(self.document.source,path),ready)
        return "queued"

    @Slot(result=str)
    def togglePreview(self):
        if not self.document or self.busy:return "unavailable"
        if self.preview_path:
            self.preview_path=None;self.images.clear();self._emit_state();self.requestPage(self.page,"preview");return "editor"
        snapshot=copy.deepcopy(self.document);path=Path(self.temp.name)/"filled-preview.pdf";request_id=uuid.uuid4().hex
        def ready(_result):
            self.preview_path=str(path);self.images.clear();self._emit_state();self.requestPage(self.page,"preview");self._emit("notice",message="Sample PDF preview ready. Saved field values have not changed.")
        self._start(request_id,lambda:engine.export_pdf(snapshot,path,sample=True),ready)
        return "queued"

    @Slot(result=str)
    def saveProject(self):
        if not self.document or self.busy:return "unavailable"
        path=self.project_path
        if not path:
            path,_=QFileDialog.getSaveFileName(None,"Save editable project",str(Path(self.document.source).with_suffix(".formstudio.json")),"Form Studio project (*.formstudio.json)")
        if not path:return "cancelled"
        try:
            engine.save_project(self.document,path);self.project_path=path;self.dirty=False;self._emit_state();self._emit("notice",message="Editable project saved.");return "ok"
        except Exception as exc:self._emit("error",message=str(exc));return str(exc)

    @Slot(result=str)
    def exportPDF(self):
        if not self.document or self.busy:return "unavailable"
        path,_=QFileDialog.getSaveFileName(None,"Export fillable PDF",str(Path(self.document.source).with_name(Path(self.document.source).stem+"_fillable.pdf")),"PDF (*.pdf)")
        if not path:return "cancelled"
        snapshot=copy.deepcopy(self.document);report=copy.deepcopy(self.report);request_id=uuid.uuid4().hex
        def operation():
            result=engine.export_pdf(snapshot,path)
            engine.save_project(snapshot,Path(path).with_suffix(".formstudio.json"))
            if report:Path(path).with_suffix(".report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            return result
        def ready(result):
            self._emit("notice",message=f"Verified {result['fields']} fields and {result['widgets']} widgets. Saved editable project beside the PDF.",details=result)
        self._start(request_id,operation,ready)
        return "queued"

    @Slot(str, result=str)
    def chooseColor(self, initial):
        color=QColorDialog.getColor(QColor(initial or "#b99af1"),None,"Choose field color")
        return color.name() if color.isValid() else ""

    def shutdown(self):
        self.pool.waitForDone()
        self.temp.cleanup()


class LocalPage(QWebEnginePage):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root=root.resolve()

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.scheme() in {"qrc", "data", "blob"}:
            return True
        if not url.isLocalFile():
            return False
        try:
            target=Path(url.toLocalFile()).resolve()
            return target==self.root or self.root in target.parents
        except (OSError,ValueError):
            return False


class StudioView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge=Bridge(self)
        root=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parent))
        self.setPage(LocalPage(root/'ui'/'dist',self))
        self.channel=QWebChannel(self.page())
        self.channel.registerObject("pdfStudio",self.bridge)
        self.page().setWebChannel(self.channel)
        self.page().setBackgroundColor(QColor("#17171b"))
        settings=self.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls,True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in {".pdf", ".json"} for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if Path(url.toLocalFile()).suffix.lower() in {".pdf", ".json"}]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.bridge.open_path(paths[0])

    def load_ui(self, root: Path):
        index=(root/"ui"/"dist"/"index.html").resolve()
        if not index.is_file():
            raise FileNotFoundError(f"Vite UI build is missing: {index}. Run npm run build in ui/.")
        self.load(QUrl.fromLocalFile(str(index)))
