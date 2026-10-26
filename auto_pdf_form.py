"""Command-line PDF form analysis and automatic repair/creation."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from engine import analyze, export_pdf, load_document, render_page, save_project, transfer_template


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path,help='Searchable PDF to analyze (the source is never overwritten)')
    parser.add_argument('-o','--output',type=Path,help='Output PDF; default: INPUT_auto_fillable.pdf')
    parser.add_argument('--template',type=Path,help='Transfer all fields from a PDF with exactly matching source artwork')
    parser.add_argument('--analyze-only',action='store_true',help='Write the JSON report without changing a PDF')
    parser.add_argument('--add-missing',action='store_true',help='Also discover additional fields in a PDF that already has fields')
    parser.add_argument('--no-auto-template',action='store_true',help='Ignore a same-layout sibling INPUT_fillable.pdf and use generic detection')
    parser.add_argument('--preview',action='store_true',help='Create a sample-filled PDF and PNG previews of changed pages')
    parser.add_argument('--font-size',type=float,help='Set all detected/repaired text fields to this size (1-100 pt)')
    parser.add_argument('--report',type=Path,help='JSON analysis report location')
    args=parser.parse_args(argv)
    out=args.output or args.input.with_name(args.input.stem+'_auto_fillable.pdf')
    report_path=args.report or out.with_suffix('.report.json')
    try:
        doc=transfer_template(args.input,args.template) if args.template else load_document(args.input)
        if args.font_size is not None:
            if not 1<=args.font_size<=100:raise ValueError('Font size must be 1-100 points.')
            for f in doc.fields:
                if f.kind in ('text','choice'):f.font_size=args.font_size
        doc,report=analyze(doc,discover=True if args.add_missing else None,prefer_template=not args.no_auto_template)
        if args.font_size is not None:
            for f in doc.fields:
                if f.kind in ('text','choice'):f.font_size=args.font_size
            doc,resized=analyze(doc,discover=False,prefer_template=False)
            report['changes'].extend(resized['changes'])
        if not args.analyze_only:
            report['export']=export_pdf(doc,out)
            save_project(doc,out.with_suffix('.formstudio.json'))
            if args.preview:
                sample=out.with_name(out.stem+'_sample.pdf');export_pdf(doc,sample,sample=True)
                pages=sorted({f.page for f in doc.fields})
                previews=out.with_name(out.stem+'_previews');previews.mkdir(parents=True,exist_ok=True)
                for index in pages:render_page(sample,index,1.4,True).save(previews/f'page_{index+1:03}.png')
                report['sample_pdf']=str(sample.resolve());report['preview_folder']=str(previews.resolve())
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'report':str(report_path.resolve()),'changes':len(report['changes']),'review_items':len(report['review']),'widgets':len(doc.fields),'output':None if args.analyze_only else str(out.resolve())},indent=2))
        return 0
    except Exception as error:
        print(f'Error: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
