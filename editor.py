"""Native PySide6 PDF field editor. PDF analysis and rendering run off the UI thread."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QObject, Signal, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QPainter, QPen, QBrush, QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QListWidget, QListWidgetItem, QGraphicsView,
    QGraphicsScene, QGraphicsObject, QFormLayout, QDoubleSpinBox, QSpinBox,
    QLineEdit, QPlainTextEdit, QCheckBox, QComboBox, QColorDialog, QFileDialog,
    QMessageBox, QScrollArea, QDialog, QDialogButtonBox, QInputDialog, QFrame,
)

from engine import (
    Document, Field, FONT_ASCENT, analyze, export_pdf, load_document,
    load_project, render_page, save_project, transfer_template,
)


STYLE = '''
QWidget { background: #1b1b20; color: #dedce5; font-family: "Segoe UI"; font-size: 12px; }
QMainWindow { background: #17171b; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #f0eef5; }
QLabel#eyebrow { color: #99939f; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#muted { color: #a39dab; }
QLabel#section { color: #e9e5f0; font-weight: 600; font-size: 13px; }
QPushButton { background: #2b2932; border: 1px solid #423d4e; border-radius: 6px; padding: 7px 11px; }
QPushButton:hover { background: #3c3549; border-color: #87709f; }
QPushButton:pressed { background: #25212d; }
QPushButton:disabled { color: #756d7e; background: #242229; border-color: #343039; }
QPushButton#primary { background: #b99af1; color: #281c3c; border-color: #b99af1; font-weight: 700; }
QPushButton#primary:hover { background: #ceb2ff; }
QPushButton#auto { background: #392d4c; color: #ddc7ff; border-color: #77589e; }
QPushButton:checked { background: #58416e; border-color: #b99af1; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #141418; border: 1px solid #423c4c; border-radius: 5px; padding: 5px; selection-background-color: #6a4c86; }
QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus { border-color: #b99af1; }
QListWidget { border: none; background: #1b1b20; outline: none; }
QListWidget::item { border-radius: 5px; padding: 8px; margin: 1px 3px; }
QListWidget::item:selected { background: #3b2e4b; color: #ddc5ff; }
QListWidget::item:hover { background: #2c2833; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #73657e; border-radius: 3px; background: #18151d; }
QCheckBox::indicator:checked { background: #b99af1; border-color: #b99af1; }
QScrollArea { border: none; }
QSplitter::handle { background: #3a333f; width: 1px; }
QStatusBar { background: #17151c; color: #aaa0b5; border-top: 1px solid #3c3345; }
QToolTip { background: #362b43; color: #f3ecff; border: 1px solid #806595; padding: 5px; }
QDialog { background: #24202c; }
'''


class Signals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__(); self.fn=fn; self.signals=Signals()

    def run(self):
        try:self.signals.result.emit(self.fn())
        except Exception as exc:self.signals.error.emit(str(exc))
        finally:self.signals.finished.emit()


class Canvas(QGraphicsView):
    zoom_requested = Signal(float)

    def wheelEvent(self,event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_requested.emit(1.15 if event.angleDelta().y()>0 else 1/1.15);event.accept()
        else:super().wheelEvent(event)


class FieldItem(QGraphicsObject):
    def __init__(self, studio, spec):
        super().__init__();self.studio=studio;self.spec=spec
        height=studio.document.sizes[spec.page][1]
        x0,y0,x1,y1=spec.rect
        self.box=QRectF(0,0,x1-x0,y1-y0);self.setPos(x0,height-y1)
        self.setFlags(QGraphicsObject.ItemIsSelectable|QGraphicsObject.ItemIsMovable|QGraphicsObject.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True);self.setZValue(10)
        self.drag_corner=None;self.start_box=None;self.start_pos=None;self.start_scene=None
        self.setToolTip(f'{spec.name}\n{spec.kind} · drag to move · drag a corner to resize')

    def boundingRect(self):return self.box.adjusted(-8,-23,8,8)

    def shape(self):
        from PySide6.QtGui import QPainterPath
        p=QPainterPath();p.addRect(self.box.adjusted(-3,-3,3,3));return p

    def _corners(self):return [self.box.topLeft(),self.box.topRight(),self.box.bottomLeft(),self.box.bottomRight()]

    def _near_corner(self,point):
        if not self.isSelected():return None
        tolerance=7/max(.2,self.studio.view.transform().m11())
        return next((i for i,p in enumerate(self._corners()) if abs(point.x()-p.x())<tolerance and abs(point.y()-p.y())<tolerance),None)

    def hoverMoveEvent(self,event):
        corner=self._near_corner(event.pos())
        self.setCursor(Qt.SizeFDiagCursor if corner in (0,3) else Qt.SizeBDiagCursor if corner in (1,2) else Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def paint(self,painter,option,widget=None):
        f=self.spec;painter.setRenderHint(QPainter.Antialiasing)
        bg=QColor(f.highlight);bg.setAlpha(43 if self.isSelected() else 19)
        painter.fillRect(self.box,bg)
        if f.background:painter.fillRect(self.box,QColor(f.background))
        pen=QPen(QColor('#d8bdff') if self.isSelected() else QColor(f.highlight));pen.setCosmetic(True)
        pen.setStyle(Qt.SolidLine if self.isSelected() else Qt.DashLine);painter.setPen(pen);painter.drawRect(self.box)
        painter.save();painter.setClipRect(self.box.adjusted(.3,.3,-.3,-.3));painter.setPen(QColor(f.text_color))
        if f.kind in ('checkbox','radio') and f.checked:
            cross=QPen(QColor(f.text_color),max(1,min(self.box.width(),self.box.height())*.12));cross.setCapStyle(Qt.RoundCap)
            painter.setPen(cross);r=self.box.adjusted(self.box.width()*.2,self.box.height()*.2,-self.box.width()*.2,-self.box.height()*.2)
            painter.drawLine(r.topLeft(),r.bottomRight());painter.drawLine(r.topRight(),r.bottomLeft())
        elif f.kind in ('text','choice'):
            font=QFont({'Helvetica':'Arial','Times-Roman':'Times New Roman','Courier':'Courier New'}.get(f.font,'Arial'));font.setPixelSize(max(1,round(f.font_size)));painter.setFont(font)
            if f.multiline:painter.drawText(self.box.adjusted(2,2,-2,-2),Qt.AlignTop|Qt.AlignLeft|Qt.TextWordWrap,f.value)
            else:
                baseline=(self.box.height()+FONT_ASCENT.get(f.font,718)*f.font_size/1000)/2
                width=painter.fontMetrics().horizontalAdvance(f.value)
                x=(self.box.width()-width)/2 if f.alignment==1 else self.box.width()-width-2 if f.alignment==2 else 2
                painter.drawText(QPointF(x,baseline),f.value)
        painter.restore()
        if self.isSelected():
            painter.setPen(QColor('#f0e4ff'));font=QFont('Segoe UI');font.setPixelSize(9);painter.setFont(font)
            painter.fillRect(QRectF(0,-18,min(260,max(75,len(f.name)*5.2)),15),QColor('#382447'))
            painter.drawText(QPointF(4,-7),f.name[:46])
            painter.setBrush(QColor('#d8bdff'));painter.setPen(Qt.NoPen)
            size=5/max(.3,self.studio.view.transform().m11())
            for p in self._corners():painter.drawRect(QRectF(p.x()-size/2,p.y()-size/2,size,size))

    def mousePressEvent(self,event):
        if self.studio.busy:event.ignore();return
        self.start_pos=QPointF(self.pos());self.start_box=QRectF(self.box);self.start_scene=event.scenePos()
        self.drag_corner=self._near_corner(event.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.drag_corner is None:
            super().mouseMoveEvent(event)
            pw,ph=self.studio.document.sizes[self.spec.page]
            self.setPos(max(0,min(pw-self.box.width(),self.x())),max(0,min(ph-self.box.height(),self.y())))
            return
        delta=event.scenePos()-self.start_scene
        left=self.start_pos.x();top=self.start_pos.y();right=left+self.start_box.width();bottom=top+self.start_box.height()
        if self.drag_corner in (0,2):left=min(right-5,left+delta.x())
        else:right=max(left+5,right+delta.x())
        if self.drag_corner in (0,1):top=min(bottom-5,top+delta.y())
        else:bottom=max(top+5,bottom+delta.y())
        pw,ph=self.studio.document.sizes[self.spec.page]
        left=max(0,left);top=max(0,top);right=min(pw,right);bottom=min(ph,bottom)
        self.prepareGeometryChange();self.setPos(left,top);self.box=QRectF(0,0,right-left,bottom-top);self.update()

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if self.start_pos is None:return
        height=self.studio.document.sizes[self.spec.page][1]
        rect=[self.x(),height-self.y()-self.box.height(),self.x()+self.box.width(),height-self.y()]
        if max(abs(x-y) for x,y in zip(rect,self.spec.rect))>.02:
            key=self.spec.key;studio=self.studio;QTimer.singleShot(0,lambda:studio.change_geometry(key,rect))
        self.drag_corner=None;self.start_pos=None

    def mouseDoubleClickEvent(self,event):
        f=self.spec
        if f.kind in ('checkbox','radio'):self.studio.toggle_checked(f.key)
        else:
            value,ok=QInputDialog.getMultiLineText(self.studio,'Field value',f.name,f.value)
            if ok:self.studio.change_value(f.key,value)
        event.accept()


class Studio(QMainWindow):
    document_loaded = Signal()

    def __init__(self):
        super().__init__();self.setWindowTitle('Auto PDF Form — Form Studio');self.resize(1480,940)
        self.setMinimumSize(1080,700);self.setAcceptDrops(True)
        self.document=None;self.page=0;self.selected=None;self.syncing=False;self.busy=False
        self.dirty=False;self.force_close=False;self.history=[];self.redo_history=[];self.project_path=None
        self.latest_report=None;self.preview_path=None;self.pdf_cache={};self.jobs=set();self.render_token=0
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(3)
        self.temp=tempfile.TemporaryDirectory(prefix='PDFFormStudio_')
        self.setStyleSheet(STYLE)
        self._build();self._shortcuts();self._enable(False)

    def _label(self,text,style=None):
        label=QLabel(text)
        if style:label.setObjectName(style)
        return label

    def _button(self,text,callback,object_name=None):
        button=QPushButton(text);button.clicked.connect(callback)
        if object_name:button.setObjectName(object_name)
        return button

    def _build(self):
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(18,14,18,10);layout.setSpacing(12);self.setCentralWidget(root)
        header=QHBoxLayout()
        logo_path=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'/'logo-wordmark.png'
        if logo_path.exists():
            logo=QLabel();logo.setPixmap(QPixmap(str(logo_path)).scaledToHeight(48,Qt.SmoothTransformation));logo.setFixedHeight(48);header.addWidget(logo)
        else:header.addWidget(self._label('Form Studio','brand'))
        header.addSpacing(12);header.addWidget(self._label('LOCAL PDF EDITOR','eyebrow'));header.addStretch()
        self.file_label=self._label('Open a PDF to start','muted');header.addWidget(self.file_label);layout.addLayout(header)
        toolbar=QHBoxLayout();toolbar.setSpacing(7)
        self.open_btn=self._button('Open PDF…',self.open_dialog);toolbar.addWidget(self.open_btn)
        self.save_btn=self._button('Save project',self.save_project_dialog);toolbar.addWidget(self.save_btn)
        self.export_btn=self._button('Export PDF…',self.export_dialog,'primary');toolbar.addWidget(self.export_btn)
        toolbar.addSpacing(8);self.auto_btn=self._button('✦  Automatic',self.auto_detect,'auto');toolbar.addWidget(self.auto_btn)
        self.template_btn=self._button('Template…',self.import_template);toolbar.addWidget(self.template_btn)
        self.preview_btn=self._button('Filled preview',self.toggle_preview);self.preview_btn.setCheckable(True);toolbar.addWidget(self.preview_btn)
        self.report_btn=self._button('Analysis report',self.show_report);toolbar.addWidget(self.report_btn)
        toolbar.addStretch();self.undo_btn=self._button('Undo',self.undo);self.redo_btn=self._button('Redo',self.redo);toolbar.addWidget(self.undo_btn);toolbar.addWidget(self.redo_btn)
        layout.addLayout(toolbar)
        self.splitter=QSplitter();layout.addWidget(self.splitter,1)
        left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,4,10,0)
        self.pages_label=self._label('PAGES','eyebrow');ll.addWidget(self.pages_label)
        self.pages=QListWidget();self.pages.setMaximumHeight(245);self.pages.currentRowChanged.connect(self.set_page);ll.addWidget(self.pages)
        ll.addSpacing(12);self.fields_label=self._label('FIELDS ON THIS PAGE','eyebrow');ll.addWidget(self.fields_label)
        field_tools=QVBoxLayout();field_tools.setSpacing(6);self.field_search=QLineEdit();self.field_search.setPlaceholderText('Search field names…');self.field_search.textChanged.connect(self.fill_field_list);field_tools.addWidget(self.field_search)
        self.field_type=QComboBox();self.field_type.addItems(['All types','Text','Dropdown','Checkbox','Radio']);self.field_type.setToolTip('Filter the page by field category');self.field_type.currentIndexChanged.connect(self.fill_field_list);field_tools.addWidget(self.field_type);ll.addLayout(field_tools)
        self.field_list=QListWidget();self.field_list.currentItemChanged.connect(self.select_list_field);ll.addWidget(self.field_list,1)
        self.delete_btn=self._button('Delete selected',self.delete_selected);ll.addWidget(self.delete_btn);self.splitter.addWidget(left)
        middle=QWidget();ml=QVBoxLayout(middle);ml.setContentsMargins(0,0,0,0);ml.setSpacing(8)
        tools=QHBoxLayout();self.page_label=self._label('Canvas','section');tools.addWidget(self.page_label);tools.addStretch()
        self.add_text=self._button('+ Text',lambda:self.add_field('text'));self.add_check=self._button('+ Checkbox',lambda:self.add_field('checkbox'));self.add_radio=self._button('+ Radio',lambda:self.add_field('radio'))
        for b in (self.add_text,self.add_check,self.add_radio):tools.addWidget(b)
        self.fit_btn=self._button('Fit width',self.fit_width);tools.addWidget(self.fit_btn)
        self.zoom=QComboBox();self.zoom.addItems(['50%','75%','100%','125%','150%','200%']);self.zoom.setCurrentText('100%');self.zoom.currentTextChanged.connect(self.zoom_to);self.zoom.setFixedWidth(82);tools.addWidget(self.zoom);ml.addLayout(tools)
        self.scene=QGraphicsScene(self);self.scene.selectionChanged.connect(self.selection_changed)
        self.view=Canvas(self.scene);self.view.setBackgroundBrush(QColor('#35333b'));self.view.setFrameShape(QFrame.NoFrame);self.view.setAlignment(Qt.AlignHCenter|Qt.AlignTop);self.view.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform);self.view.zoom_requested.connect(self.zoom_by)
        self.scene.addText('Open a PDF, or drop one here.\n\nExisting fields load automatically.\nBlank forms can be detected with Automatic.').setDefaultTextColor(QColor('#d9e5ed'))
        ml.addWidget(self.view,1);ml.addWidget(self._label('Drag fields to move • Drag corners to resize • Double-click to fill • Ctrl + wheel to zoom','muted'));self.splitter.addWidget(middle)
        self.inspector_scroll=QScrollArea();self.inspector_scroll.setWidgetResizable(True);inspector=QWidget();il=QVBoxLayout(inspector);il.setContentsMargins(15,4,1,5);il.setSpacing(10)
        il.addWidget(self._label('FIELD SETTINGS','eyebrow'));self.selection_label=self._label('Select a field','section');il.addWidget(self.selection_label)
        self.controls=QWidget();cl=QVBoxLayout(self.controls);cl.setContentsMargins(0,0,0,0);cl.setSpacing(14);il.addWidget(self.controls)
        form=QFormLayout();form.setSpacing(8);self.name_edit=QLineEdit();self.name_edit.editingFinished.connect(self.commit_inspector);form.addRow('Name',self.name_edit)
        self.tooltip_edit=QLineEdit();self.tooltip_edit.editingFinished.connect(self.commit_inspector);form.addRow('Tooltip',self.tooltip_edit);cl.addLayout(form)
        cl.addWidget(self._label('Position & size  ·  points','section'));geometry=QFormLayout();self.geometry={}
        for name in ('X','Y from top','Width','Height'):
            spin=QDoubleSpinBox();spin.setRange(0,10000);spin.setDecimals(2);spin.setSingleStep(1);spin.editingFinished.connect(self.commit_inspector);self.geometry[name]=spin;geometry.addRow(name,spin)
        cl.addLayout(geometry);textform=QFormLayout();self.font_combo=QComboBox();self.font_combo.addItems(['Helvetica','Times-Roman','Courier']);self.font_combo.currentTextChanged.connect(self.commit_inspector);textform.addRow('Font',self.font_combo)
        self.font_size=QDoubleSpinBox();self.font_size.setRange(1,100);self.font_size.setSuffix(' pt');self.font_size.editingFinished.connect(self.commit_inspector);textform.addRow('Text size',self.font_size)
        self.align_combo=QComboBox();self.align_combo.addItems(['Left','Center','Right']);self.align_combo.currentIndexChanged.connect(self.commit_inspector);textform.addRow('Alignment',self.align_combo)
        self.max_chars=QSpinBox();self.max_chars.setRange(0,100000);self.max_chars.setSpecialValueText('Unlimited');self.max_chars.editingFinished.connect(self.commit_inspector);textform.addRow('Max characters',self.max_chars)
        self.multiline=QCheckBox('Allow multiple lines');self.multiline.toggled.connect(self.commit_inspector);textform.addRow(self.multiline);cl.addLayout(textform)
        cl.addWidget(self._label('Appearance','section'));colors=QFormLayout();self.color_buttons={}
        for prop,label in (('text_color','Text / X color'),('highlight','Editor highlight'),('background','PDF background'),('border_color','PDF border')):
            button=QPushButton();button.clicked.connect(lambda checked=False,p=prop:self.choose_color(p));self.color_buttons[prop]=button;colors.addRow(label,button)
        self.transparent=QCheckBox('Transparent PDF background');self.transparent.toggled.connect(self.commit_inspector);colors.addRow(self.transparent)
        self.border_width=QDoubleSpinBox();self.border_width.setRange(0,10);self.border_width.setSingleStep(.25);self.border_width.editingFinished.connect(self.commit_inspector);colors.addRow('Border width',self.border_width);cl.addLayout(colors)
        explanation=self._label('Editor highlights are only shown here. PDF background and border colors are exported. Each PDF reader controls its own temporary blue highlighting.','muted');explanation.setWordWrap(True);cl.addWidget(explanation)
        self.group_edit=QLineEdit();self.option_edit=QLineEdit();self.checked_box=QCheckBox('Selected');self.checked_box.toggled.connect(self.commit_inspector);self.group_edit.editingFinished.connect(self.commit_inspector);self.option_edit.editingFinished.connect(self.commit_inspector)
        groupform=QFormLayout();groupform.addRow('Radio group',self.group_edit);groupform.addRow('Option value',self.option_edit);groupform.addRow(self.checked_box);cl.addLayout(groupform)
        cl.addWidget(self._label('Saved value','section'));self.value_edit=QPlainTextEdit();self.value_edit.setMaximumHeight(100);self.value_edit.setPlaceholderText('Double-click a field to fill it, or type here.');cl.addWidget(self.value_edit)
        self.apply_value_btn=self._button('Apply value',self.commit_inspector);cl.addWidget(self.apply_value_btn)
        cl.addWidget(self._label('Dropdown options · one per line','muted'));self.choices_edit=QPlainTextEdit();self.choices_edit.setMaximumHeight(75);cl.addWidget(self.choices_edit)
        self.apply_options=self._button('Apply options',self.commit_inspector);cl.addWidget(self.apply_options)
        self.duplicate_btn=self._button('Duplicate selected',self.duplicate_selected);cl.addWidget(self.duplicate_btn)
        il.addStretch();self.inspector_scroll.setWidget(inspector);self.splitter.addWidget(self.inspector_scroll);self.splitter.setSizes([215,900,300]);self.splitter.setStretchFactor(1,1)
        self.statusBar().showMessage('Ready • All processing stays on this computer')

    def _shortcuts(self):
        for shortcut,callback in (('Ctrl+O',self.open_dialog),('Ctrl+S',self.save_project_dialog),('Ctrl+Shift+S',self.export_dialog),('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),('Delete',self.delete_selected),('Ctrl+D',self.duplicate_selected)):
            action=QAction(self);action.setShortcut(QKeySequence(shortcut));action.triggered.connect(callback);self.addAction(action)

    def _enable(self,loaded):
        editable=loaded and not self.preview_path and not self.busy
        for button in (self.save_btn,self.export_btn,self.auto_btn,self.template_btn,self.add_text,self.add_check,self.add_radio,self.delete_btn):button.setEnabled(editable)
        self.preview_btn.setEnabled(loaded and not self.busy);self.fit_btn.setEnabled(loaded);self.zoom.setEnabled(loaded)
        self.report_btn.setEnabled(self.latest_report is not None and not self.busy)
        self.controls.setEnabled(editable and self.selected is not None)
        self.undo_btn.setEnabled(editable and bool(self.history));self.redo_btn.setEnabled(editable and bool(self.redo_history))

    def _run(self,fn,success,message):
        self.busy=True;self._enable(self.document is not None);self.statusBar().showMessage(message)
        job=Job(fn);self.jobs.add(job)
        def done():
            self.jobs.discard(job);self.busy=False;self._enable(self.document is not None)
        job.signals.finished.connect(done);job.signals.result.connect(success);job.signals.error.connect(lambda text:self.error(text));self.pool.start(job)

    def error(self,text):
        self.statusBar().showMessage('Operation could not be completed.');QMessageBox.warning(self,'PDF Form Studio',text)

    def _confirm_discard(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self,'Unsaved project','Save the editable project before opening another file?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
        if answer==QMessageBox.Save:return self.save_project_dialog()
        return answer==QMessageBox.Discard

    def open_dialog(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'Open PDF or project','','PDF or project (*.pdf *.formstudio.json);;PDF (*.pdf);;Project (*.formstudio.json)')
        if path:self.open_path(path)

    def open_path(self,path):
        if not self._confirm_discard():return
        self.preview_path=None;self.preview_btn.setChecked(False)
        def loaded(doc):
            self.document=doc;self.page=0;self.selected=None;self.history.clear();self.redo_history.clear();self.latest_report=None;self.pdf_cache.clear();self.dirty=False
            self.project_path=str(path) if str(path).endswith('.json') else None
            self.pages.blockSignals(True);self.pages.clear()
            for i in range(len(doc.sizes)):self.pages.addItem(f'{i+1:02}   Page {i+1}')
            self.pages.setCurrentRow(0);self.pages.blockSignals(False);self.pages_label.setText(f'PAGES  ·  {len(doc.sizes)}');self.file_label.setText(Path(doc.source).name)
            self.statusBar().showMessage(f'Opened {len(doc.sizes)} pages · {len(doc.fields)} field widgets');self.refresh_page(fit=True);self.document_loaded.emit()
            if doc.unsupported:self.error('This PDF can be viewed, but editing/export is blocked:\n\n'+'\n'.join(doc.unsupported))
        self._run(lambda:load_project(path) if str(path).lower().endswith('.json') else load_document(path),loaded,'Opening PDF…')

    def set_page(self,index):
        if not self.document or index<0:return
        self.page=index;self.selected=None;self.refresh_page(fit=True)

    def refresh_page(self,fit=False):
        if not self.document:return
        self.render_token+=1;token=self.render_token;page=self.page;path=self.preview_path or self.document.source
        scroll=self.view.verticalScrollBar().value()
        forms=bool(self.preview_path)
        key=(str(path),page,bool(self.preview_path))
        self.scene.blockSignals(True);self.scene.clear();self.scene.blockSignals(False)
        self.page_label.setText(f'{"Sample preview" if self.preview_path else "Page"} {page+1} / {len(self.document.sizes)}')
        self.fill_field_list();self.fill_inspector()
        pw,ph=self.document.sizes[page];self.scene.setSceneRect(-12,-12,pw+24,ph+24)
        def show(image):
            if token!=self.render_token:return
            raw=image.tobytes();qimage=QImage(raw,image.width,image.height,image.width*3,QImage.Format_RGB888).copy()
            pix=self.scene.addPixmap(QPixmap.fromImage(qimage));pix.setScale(pw/image.width);pix.setZValue(-10)
            if not self.preview_path:
                for spec in self.document.fields:
                    if spec.page==self.page:
                        item=FieldItem(self,spec);self.scene.addItem(item)
                        if spec.key==self.selected:item.setSelected(True)
            if fit:self.fit_width()
            else:self.view.verticalScrollBar().setValue(scroll)
        if key in self.pdf_cache:show(self.pdf_cache[key])
        else:
            job=Job(lambda:render_page(path,page,1.6,forms));self.jobs.add(job)
            def rendered(image):
                self.pdf_cache[key]=image
                if len(self.pdf_cache)>12:self.pdf_cache.pop(next(iter(self.pdf_cache)))
                show(image)
            job.signals.result.connect(rendered);job.signals.error.connect(self.error);job.signals.finished.connect(lambda:self.jobs.discard(job));self.pool.start(job)
        self._enable(True)

    def fit_width(self):
        if not self.document:return
        self.view.resetTransform();factor=max(.15,(self.view.viewport().width()-36)/self.document.sizes[self.page][0]);self.view.scale(factor,factor)
        self.zoom.blockSignals(True);self.zoom.setEditable(True);self.zoom.setCurrentText(f'{round(factor*100)}%');self.zoom.setEditable(False);self.zoom.blockSignals(False)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())

    def zoom_to(self,text):
        try:factor=float(text.strip('%'))/100
        except ValueError:return
        self.view.resetTransform();self.view.scale(factor,factor)

    def zoom_by(self,factor):
        new=max(.2,min(4,self.view.transform().m11()*factor));self.view.resetTransform();self.view.scale(new,new)

    def fill_field_list(self):
        self.field_list.blockSignals(True);self.field_list.clear()
        if self.document:
            specs=[f for f in self.document.fields if f.page==self.page]
            kinds={0:None,1:'text',2:'choice',3:'checkbox',4:'radio'}
            kind=kinds.get(self.field_type.currentIndex()) if hasattr(self,'field_type') else None
            query=self.field_search.text().strip().casefold() if hasattr(self,'field_search') else ''
            visible=[f for f in specs if (kind is None or f.kind==kind) and (not query or query in f.name.casefold() or query in f.tooltip.casefold() or query in f.option.casefold())]
            self.fields_label.setText(f'FIELDS ON PAGE  ·  {len(visible)} / {len(specs)}')
            for f in visible:
                item=QListWidgetItem(('○ ' if f.kind=='radio' else '☒ ' if f.kind=='checkbox' else 'T  ')+f.name+(' · '+f.option if f.kind=='radio' else ''))
                item.setData(Qt.UserRole,f.key);self.field_list.addItem(item)
                if f.key==self.selected:self.field_list.setCurrentItem(item)
        self.field_list.blockSignals(False)

    def current(self):return next((f for f in self.document.fields if f.key==self.selected),None) if self.document else None

    def select_list_field(self,current,previous):
        if current is None:return
        self.selected=current.data(Qt.UserRole)
        self.scene.blockSignals(True)
        for item in self.scene.items():
            if isinstance(item,FieldItem):
                item.setSelected(item.spec.key==self.selected)
                if item.spec.key==self.selected:self.view.ensureVisible(item,25,25)
        self.scene.blockSignals(False);self.fill_inspector()

    def selection_changed(self):
        items=[i for i in self.scene.selectedItems() if isinstance(i,FieldItem)]
        self.selected=items[0].spec.key if items else None;self.fill_field_list();self.fill_inspector()

    def fill_inspector(self):
        self.syncing=True;f=self.current();self.selection_label.setText(f.kind.capitalize()+' field' if f else 'Select a field')
        self.controls.setEnabled(f is not None and not self.preview_path and not self.busy)
        if f:
            self.name_edit.setText(f.name);self.tooltip_edit.setText(f.tooltip);pw,ph=self.document.sizes[f.page]
            for key,value in zip(('X','Y from top','Width','Height'),(f.rect[0],ph-f.rect[3],f.rect[2]-f.rect[0],f.rect[3]-f.rect[1])):self.geometry[key].setValue(value)
            self.font_size.setValue(f.font_size);self.font_combo.setCurrentText(f.font);self.align_combo.setCurrentIndex(f.alignment);self.max_chars.setValue(f.max_length);self.multiline.setChecked(f.multiline);self.border_width.setValue(f.border_width)
            self.transparent.setChecked(f.background is None)
            for prop,button in self.color_buttons.items():
                color=getattr(f,prop) or '#ffffff';button.setText(color);button.setProperty('color',color);button.setStyleSheet(f'background: {color}; color: {"#152030" if QColor(color).lightness()>135 else "#f1f5fa"};')
            self.group_edit.setText(f.group);self.option_edit.setText(f.option);self.checked_box.setChecked(f.checked);self.value_edit.setPlainText(f.value);self.choices_edit.setPlainText('\n'.join(f.choices))
            is_text=f.kind in ('text','choice')
            for control in (self.font_size,self.font_combo,self.align_combo,self.max_chars,self.multiline,self.value_edit,self.apply_value_btn):control.setEnabled(is_text)
            self.group_edit.setEnabled(f.kind=='radio');self.option_edit.setEnabled(f.kind in ('radio','checkbox'));self.checked_box.setEnabled(f.kind in ('radio','checkbox'))
            self.choices_edit.setEnabled(f.kind=='choice');self.apply_options.setEnabled(f.kind=='choice')
        self.syncing=False;self._enable(self.document is not None)

    def _edit(self,mutate):
        if not self.document or self.busy or self.preview_path:return
        before=copy.deepcopy(self.document.fields)
        mutate()
        if before==self.document.fields:return
        self.history.append(before);self.history=self.history[-100:];self.redo_history.clear();self.dirty=True
        self.setWindowTitle('PDF Form Studio • Unsaved project');self.refresh_page()

    def commit_inspector(self,*args):
        if self.syncing or not self.current():return
        def mutate():
            f=self.current();pw,ph=self.document.sizes[f.page]
            width=max(3,min(pw,self.geometry['Width'].value()));height=max(3,min(ph,self.geometry['Height'].value()))
            left=max(0,min(pw-width,self.geometry['X'].value()));top=max(0,min(ph-height,self.geometry['Y from top'].value()))
            f.rect=[left,ph-top-height,left+width,ph-top];f.name=self.name_edit.text().strip();f.tooltip=self.tooltip_edit.text()
            f.font_size=self.font_size.value();f.font=self.font_combo.currentText();f.alignment=self.align_combo.currentIndex();f.max_length=self.max_chars.value();f.multiline=self.multiline.isChecked();f.border_width=self.border_width.value()
            for prop,button in self.color_buttons.items():setattr(f,prop,button.property('color'))
            if self.transparent.isChecked():f.background=None
            f.value=self.value_edit.toPlainText();f.group=self.group_edit.text().strip();f.option=self.option_edit.text().strip();f.checked=self.checked_box.isChecked();f.choices=self.choices_edit.toPlainText().splitlines()
            if f.kind=='radio':
                f.name=f.group
                if f.checked:
                    for other in self.document.fields:
                        if other.key!=f.key and other.kind=='radio' and other.group==f.group:other.checked=False
        self._edit(mutate)

    def choose_color(self,prop):
        if not self.current():return
        button=self.color_buttons[prop];color=QColorDialog.getColor(QColor(button.property('color') or '#ffffff'),self,'Choose '+prop.replace('_',' '))
        if color.isValid():
            button.setProperty('color',color.name())
            if prop=='background':self.transparent.blockSignals(True);self.transparent.setChecked(False);self.transparent.blockSignals(False)
            self.commit_inspector()

    def change_geometry(self,key,rect):
        self.selected=key;self._edit(lambda:setattr(self.current(),'rect',rect))

    def change_value(self,key,value):
        self.selected=key;self._edit(lambda:setattr(self.current(),'value',value))

    def toggle_checked(self,key):
        self.selected=key
        def mutate():
            f=self.current();f.checked=not f.checked
            if f.kind=='radio' and f.checked:
                for other in self.document.fields:
                    if other.kind=='radio' and other.group==f.group and other.key!=f.key:other.checked=False
        self._edit(mutate)

    def add_field(self,kind):
        if not self.document:return
        selected=self.current();count=len(self.document.fields)+1;pw,ph=self.document.sizes[self.page]
        width,height=(170,24) if kind=='text' else (13,13)
        group=selected.group if selected and selected.kind=='radio' and kind=='radio' else f'choice_{count}'
        existing_options={f.option for f in self.document.fields if f.group==group}
        option=f'Option{len(existing_options)+1}'
        f=Field.make(group if kind=='radio' else f'field_{count}',self.page,[min(72,pw-width),max(0,ph-180),min(72,pw-width)+width,max(0,ph-180)+height],kind=kind,border_width=.7,group=group if kind=='radio' else '',option=option if kind=='radio' else 'Yes')
        def mutate():self.document.fields.append(f);self.selected=f.key
        self._edit(mutate)

    def delete_selected(self):
        if self.current():self._edit(lambda:setattr(self.document,'fields',[f for f in self.document.fields if f.key!=self.selected]));self.selected=None

    def duplicate_selected(self):
        f=self.current()
        if not f:return
        new=Field.make(f.name+'_copy',f.page,f.rect)
        values=copy.deepcopy(f.__dict__);values['key']=new.key;new.__dict__.update(values)
        if new.kind=='radio':
            new.checked=False;new.option='Option'+str(sum(f.group==new.group for f in self.document.fields)+1)
        else:
            existing={f.name for f in self.document.fields};new.name=f.name+'_copy'
            while new.name in existing:new.name+='_copy'
        pw,ph=self.document.sizes[f.page];dx=min(12,pw-new.rect[2]);dy=-min(12,new.rect[1]);new.rect=[new.rect[0]+dx,new.rect[1]+dy,new.rect[2]+dx,new.rect[3]+dy]
        def mutate():self.document.fields.append(new);self.selected=new.key
        self._edit(mutate)

    def undo(self):
        if not self.history or self.busy or self.preview_path:return
        self.redo_history.append(copy.deepcopy(self.document.fields));self.document.fields=self.history.pop();self.dirty=True;self.refresh_page()

    def redo(self):
        if not self.redo_history or self.busy or self.preview_path:return
        self.history.append(copy.deepcopy(self.document.fields));self.document.fields=self.redo_history.pop();self.dirty=True;self.refresh_page()

    def auto_detect(self):
        if not self.document or self.busy:return
        snapshot=copy.deepcopy(self.document)
        def analyzed(result):
            doc,report=result;self.history.append(copy.deepcopy(self.document.fields));self.redo_history.clear();self.document.fields=doc.fields;self.latest_report=report;self.selected=None;self.dirty=True
            self.statusBar().showMessage(f'Automatic: {len(report["changes"])} changes · {len(doc.fields)} field widgets · Review before export')
            self.refresh_page()
        self._run(lambda:analyze(snapshot),analyzed,'Finding writing lines, date segments, checkbox groups and blank response cells…')

    def show_report(self):
        if self.latest_report is None:return
        dialog=QDialog(self);dialog.setWindowTitle('Automatic analysis');dialog.resize(720,580);layout=QVBoxLayout(dialog)
        layout.addWidget(self._label(f'{len(self.latest_report["changes"])} changes · {self.latest_report["field_widgets"]} field widgets','section'))
        text=QPlainTextEdit();text.setReadOnly(True)
        lines=[f'Page {c["page"]} · {c["field"]}\n  {c["action"]}'+(' — review suggested' if c.get('confidence')=='review' else '') for c in self.latest_report['changes']]
        text.setPlainText('\n\n'.join(lines)+'\n\nREVIEW\n'+'\n'.join(self.latest_report['review']));layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def import_template(self):
        if not self.document or self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'Choose a fillable PDF with exactly matching page artwork','','PDF (*.pdf)')
        if not path:return
        source=self.document.source
        def ready(doc):
            self.history.append(copy.deepcopy(self.document.fields));self.redo_history.clear();self.document.fields=doc.fields;self.selected=None;self.dirty=True;self.refresh_page()
            self.statusBar().showMessage(f'Matching template transferred: {len(doc.fields)} widgets. Source page artwork verified.')
        self._run(lambda:transfer_template(source,path),ready,'Verifying every template page before transferring fields…')

    def toggle_preview(self):
        if not self.document:return
        if self.preview_path:
            self.preview_path=None;self.preview_btn.setText('Filled preview');self.preview_btn.setChecked(False);self.refresh_page();return
        snapshot=copy.deepcopy(self.document);path=Path(self.temp.name)/'filled-preview.pdf'
        def ready(result):
            self.preview_path=str(path);self.preview_btn.setText('Back to editor');self.preview_btn.setChecked(True);self.pdf_cache={k:v for k,v in self.pdf_cache.items() if not k[2]};self.selected=None;self.refresh_page()
            self.statusBar().showMessage('Sample preview · Blank fields are filled with examples; your saved values are preserved.')
        self._run(lambda:export_pdf(snapshot,path,sample=True),ready,'Building and verifying a sample-filled preview…')

    def save_project_dialog(self):
        if not self.document:return False
        path=self.project_path
        if not path:path,_=QFileDialog.getSaveFileName(self,'Save editable project',str(Path(self.document.source).with_suffix('.formstudio.json')),'Form Studio project (*.formstudio.json)')
        if not path:return False
        try:save_project(self.document,path)
        except Exception as exc:self.error(str(exc));return False
        self.project_path=path;self.dirty=False;self.setWindowTitle('PDF Form Studio');self.statusBar().showMessage('Project saved. Reopen this project to continue editing.');return True

    def export_dialog(self):
        if not self.document or self.busy:return
        path,_=QFileDialog.getSaveFileName(self,'Export fillable PDF',str(Path(self.document.source).with_name(Path(self.document.source).stem+'_edited.pdf')),'PDF (*.pdf)')
        if not path:return
        snapshot=copy.deepcopy(self.document)
        def operation():
            result=export_pdf(snapshot,path);save_project(snapshot,Path(path).with_suffix('.formstudio.json'))
            if self.latest_report:Path(path).with_suffix('.report.json').write_text(json.dumps(self.latest_report,indent=2),encoding='utf-8')
            return result
        def ready(result):self.statusBar().showMessage(f'Exported and verified {result["fields"]} fields · {Path(path).name} · Editable project saved beside it')
        self._run(operation,ready,'Exporting PDF and verifying saved fields, values and appearances…')

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in {'.pdf','.json'} for url in event.mimeData().urls()):event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if Path(url.toLocalFile()).suffix.lower() in {'.pdf','.json'}]
        if not paths:event.ignore();return
        event.acceptProposedAction();self.open_path(paths[0])

    def closeEvent(self,event):
        if self.force_close or self._confirm_discard():
            self.pool.waitForDone();self.temp.cleanup();event.accept()
        else:event.ignore()
