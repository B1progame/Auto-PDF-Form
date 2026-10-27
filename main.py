from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Auto PDF Form — native PDF form editor and automatic analyzer')
    parser.add_argument('file',nargs='?',help='PDF or .formstudio.json project')
    parser.add_argument('--self-test',type=Path,help='Headless packaging check; writes a JSON result here')
    args=parser.parse_args()
    if args.self_test:
        try:
            import engine
            from PySide6 import QtCore,QtGui,QtWidgets
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebChannel import QWebChannel
            import pypdfium2
            result={'ok':True,'version':engine.VERSION,'python':sys.version,'qt':QtCore.qVersion(),'pdfium':True,'web_engine':True,'web_channel':True,'frozen':bool(getattr(sys,'frozen',False))}
            if args.file:
                doc=engine.load_document(args.file)
                image=engine.render_page(doc.source,0,.5,False)
                image.save(args.self_test.with_suffix('.png'))
                doc,report=engine.analyze(doc)
                result['automatic_changes']=len(report['changes'])
                result['pdf_export']=engine.export_pdf(doc,args.self_test.with_suffix('.pdf'))
                result['source_pages']=len(doc.sizes)
            args.self_test.parent.mkdir(parents=True,exist_ok=True);args.self_test.write_text(json.dumps(result,indent=2),encoding='utf-8');return 0
        except Exception as exc:
            args.self_test.write_text(json.dumps({'ok':False,'error':str(exc)}),encoding='utf-8');return 1
    from PySide6.QtWidgets import QApplication,QMainWindow,QMenuBar,QMessageBox
    from PySide6.QtGui import QIcon,QAction
    from PySide6.QtCore import QTimer,Qt
    from web_editor import StudioView
    app=QApplication(sys.argv[:1]);app.setApplicationName('Auto PDF Form');app.setOrganizationName('PDF Form Studio')
    icon=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'app.ico'
    if icon.exists():app.setWindowIcon(QIcon(str(icon)))

    class DesktopWindow(QMainWindow):
        def __init__(self):
            super().__init__();self.view=StudioView(self);self.setCentralWidget(self.view)
            self.setWindowTitle('Auto PDF Form · Studio');self.setMinimumSize(1120,700);self.resize(1540,960)
            if icon.exists():self.setWindowIcon(QIcon(str(icon)))
            menu=self.menuBar();file_menu=menu.addMenu('&File');edit_menu=menu.addMenu('&Edit')
            for label,callback in (('&Open PDF…',self.view.bridge.openDialog),('&Save project',self.view.bridge.saveProject),('Export PDF…',self.view.bridge.exportPDF)):
                action=QAction(label,self);action.triggered.connect(callback);file_menu.addAction(action)
            file_menu.addSeparator();exit_action=QAction('E&xit',self);exit_action.triggered.connect(self.close);file_menu.addAction(exit_action)
            for label,callback in (('&Undo',self.view.bridge.undo),('&Redo',self.view.bridge.redo)):
                action=QAction(label,self);action.triggered.connect(callback);edit_menu.addAction(action)
            self.view.loadFinished.connect(self._loaded)
            self.view.load_ui(Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent)))

        def _loaded(self,ok):
            if not ok:
                QMessageBox.critical(self,'Auto PDF Form','The bundled React UI could not be loaded. Reinstall the application or rebuild the Vite UI.')
                return
            if args.file:QTimer.singleShot(150,lambda:self.view.bridge.open_path(args.file))

        def dragEnterEvent(self,event):
            if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in {'.pdf','.json'} for url in event.mimeData().urls()):event.acceptProposedAction()
            else:event.ignore()

        def dropEvent(self,event):
            paths=[url.toLocalFile() for url in event.mimeData().urls() if Path(url.toLocalFile()).suffix.lower() in {'.pdf','.json'}]
            if not paths:event.ignore();return
            event.acceptProposedAction();self.view.bridge.open_path(paths[0])

        def closeEvent(self,event):
            bridge=self.view.bridge
            if bridge.dirty:
                answer=QMessageBox.question(self,'Unsaved project','Save the editable project before closing?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
                if answer==QMessageBox.Cancel:event.ignore();return
                if answer==QMessageBox.Save and bridge.saveProject()!='ok':event.ignore();return
            bridge.shutdown();event.accept()

    window=DesktopWindow();window.setAcceptDrops(True);window.show()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
