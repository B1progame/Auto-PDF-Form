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
            import pypdfium2
            result={'ok':True,'version':engine.VERSION,'python':sys.version,'qt':QtCore.qVersion(),'pdfium':True,'frozen':bool(getattr(sys,'frozen',False))}
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
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import QTimer
    from editor import Studio
    app=QApplication(sys.argv[:1]);app.setApplicationName('Auto PDF Form');app.setOrganizationName('PDF Form Studio')
    icon=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'app.ico'
    if icon.exists():app.setWindowIcon(QIcon(str(icon)))
    window=Studio();window.show()
    if args.file:QTimer.singleShot(100,lambda:window.open_path(args.file))
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
