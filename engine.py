"""PDF analysis, field geometry, clean AcroForm export and project persistence.

Coordinates are PDF points, measured from the page's lower left. Source page
artwork is never painted over or flattened. Detection is deliberately heuristic;
the returned report records uncertain or unsupported areas for human review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, ContentStream, DecodedStreamObject,
    DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject,
)

VERSION = '1.1.0'
PDFIUM_LOCK = threading.Lock()  # PDFium is not safe for concurrent calls.
FONT_ASCENT = {'Helvetica': 718, 'Times-Roman': 683, 'Courier': 629}


@dataclass
class Field:
    key: str
    name: str
    page: int
    rect: list[float]
    kind: str = 'text'
    value: str = ''
    font_size: float = 14.0
    font: str = 'Helvetica'
    text_color: str = '#17212f'
    background: str | None = None
    border_color: str = '#64748b'
    border_width: float = 0.0
    highlight: str = '#b79af3'
    multiline: bool = False
    max_length: int = 0
    group: str = ''
    option: str = 'Yes'
    checked: bool = False
    tooltip: str = ''
    choices: list[str] = field(default_factory=list)
    alignment: int = 0
    locked: bool = False
    linked_fields: list[str] = field(default_factory=list)

    @classmethod
    def make(cls, name, page, rect, **kwargs):
        return cls(uuid.uuid4().hex, name, page, list(map(float, rect)), **kwargs)


@dataclass
class Rewrite:
    key: str
    page: int
    rect: list[float]
    text: str = ''
    font_size: float = 14.0
    font: str = 'Helvetica'
    text_color: str = '#17212f'
    fill: str = '#ffffff'

    @classmethod
    def make(cls, page, rect, **kwargs):
        return cls(uuid.uuid4().hex, page, list(map(float, rect)), **kwargs)


@dataclass
class Document:
    source: str
    sha256: str
    sizes: list[list[float]]
    fields: list[Field]
    warnings: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    rewrites: list[Rewrite] = field(default_factory=list)


@dataclass
class Anchor:
    page: int
    x0: float
    x1: float
    baseline: float
    kind: str = 'line'
    family: str = ''
    part: str = ''


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rgb(value):
    value = value.lstrip('#')
    return [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]


def color_from_pdf(values, default):
    if not values:
        return default
    v = list(map(float, values))
    if len(v) == 1:
        v *= 3
    if len(v) != 3:
        return default
    return '#' + ''.join(f'{max(0,min(255,round(n*255))):02x}' for n in v)


def inherited(obj, name, default=None):
    seen = set()
    while obj is not None and id(obj) not in seen:
        seen.add(id(obj))
        if name in obj:
            return obj[name]
        obj = obj.get('/Parent')
        if obj is not None:
            obj = obj.get_object()
    return default


def qualified(obj):
    pieces, seen = [], set()
    while obj is not None and id(obj) not in seen:
        seen.add(id(obj))
        if obj.get('/T'):
            pieces.append(str(obj['/T']))
        obj = obj.get('/Parent')
        if obj is not None:
            obj = obj.get_object()
    return '.'.join(reversed(pieces))


def load_document(path: str | Path) -> Document:
    path = Path(path).resolve()
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('This PDF is password protected. Open an unlocked copy first.')
    sizes, fields, warnings, unsupported = [], [], [], []
    canonical = reader.get_fields() or {}
    for index, page in enumerate(reader.pages):
        sizes.append([float(page.mediabox.width), float(page.mediabox.height)])
        if page.rotation or abs(float(page.mediabox.left)) > .01 or abs(float(page.mediabox.bottom)) > .01:
            unsupported.append(f'Page {index+1}: rotated or offset page coordinates; normalize the page first.')
        for ref in page.get('/Annots', []):
            obj = ref.get_object()
            if obj.get('/Subtype') != '/Widget':
                continue
            name = qualified(obj)
            ft = str(inherited(obj, '/FT', ''))
            flags = int(inherited(obj, '/Ff', 0))
            if ft == '/Sig' or (ft == '/Btn' and flags & 65536):
                unsupported.append(f'{name or "Unnamed widget"}: digital signature or pushbutton is not editable.')
                continue
            if ft not in ('/Tx', '/Btn', '/Ch'):
                unsupported.append(f'{name or "Unnamed widget"}: unsupported control {ft}.')
                continue
            if name and name not in canonical:
                unsupported.append(f'{name}: orphan widget is absent from the canonical field tree.')
            # A stale parallel field tree caused some earlier form bugs. Refuse
            # ambiguous input rather than creating duplicate fields with one name.
            parent = obj
            while parent.get('/Parent'):
                parent = parent['/Parent'].get_object()
            root = reader.trailer['/Root'].get('/AcroForm', {})
            if hasattr(root, 'get_object'): root = root.get_object()
            roots = root.get('/Fields', []) if hasattr(root, 'get') else []
            if not any(r.get_object() is parent for r in roots):
                unsupported.append(f'{name}: widget is not attached to its canonical field tree.')
            rect = list(map(float, obj.get('/Rect', [0,0,0,0])))
            value = inherited(obj, '/V', '')
            da = str(inherited(obj, '/DA', '/Helv 12 Tf 0 g'))
            font_match = re.search(r'/([^\s]+)\s+([\d.]+)\s+Tf', da)
            size = float(font_match[2]) if font_match and float(font_match[2]) > 0 else 12.0
            font = 'Helvetica'
            if font_match and 'cour' in font_match[1].lower(): font = 'Courier'
            elif font_match and 'time' in font_match[1].lower(): font = 'Times-Roman'
            mk = obj.get('/MK', {})
            bs = obj.get('/BS', {})
            text_match = re.search(r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg', da)
            gray_match = re.search(r'([\d.]+)\s+g(?:\s|$)', da)
            tc = color_from_pdf([float(x) for x in text_match.groups()], '#000000') if text_match else color_from_pdf([float(gray_match[1])], '#000000') if gray_match else '#000000'
            options = [str(k).lstrip('/') for k in obj.get('/AP', {}).get('/N', {}) if str(k) != '/Off'] if ft == '/Btn' else []
            kind = 'radio' if ft == '/Btn' and flags & 32768 else 'checkbox' if ft == '/Btn' else 'choice' if ft == '/Ch' else 'text'
            option = options[0] if options else 'Yes'
            state = str(obj.get('/AS', value or '/Off')).lstrip('/')
            choices = []
            for opt in inherited(obj, '/Opt', []):
                choices.append(str(opt[0] if isinstance(opt, (list, ArrayObject)) else opt))
            fields.append(Field.make(
                name or f'field_{len(fields)+1}', index, rect, kind=kind,
                value=str(value or '') if ft != '/Btn' else '', font_size=size, font=font,
                text_color=tc, background=color_from_pdf(mk.get('/BG'), None),
                border_color=color_from_pdf(mk.get('/BC'), '#64748b'),
                border_width=float(bs.get('/W', 0)), multiline=bool(flags & 4096),
                max_length=int(inherited(obj, '/MaxLen', 0)),
                group=name if kind == 'radio' else '', option=option,
                checked=state not in ('Off', ''), tooltip=str(inherited(obj, '/TU', name)), choices=choices,alignment=int(inherited(obj,'/Q',0)),
            ))
    return Document(str(path), digest(path), sizes, fields, warnings, list(dict.fromkeys(unsupported)))


def save_project(document: Document, path):
    data = {'format': 'PDFFormStudio', 'version': 1, 'app_version': VERSION, 'document': asdict(document)}
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def load_project(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('format') != 'PDFFormStudio' or data.get('version') != 1:
        raise ValueError('This is not a supported PDF Form Studio project.')
    doc = data['document']
    source = Path(doc['source'])
    if not source.exists():
        alternate = Path(path).parent / source.name
        if alternate.exists(): source = alternate
    if not source.exists():
        raise ValueError(f'The original PDF is missing: {source}. Keep it beside the project or at its original location.')
    if digest(source) != doc['sha256']:
        raise ValueError('The original PDF changed since this project was saved. Open the PDF as a new document.')
    doc['source'] = str(source.resolve())
    doc['fields'] = [Field(**f) for f in doc['fields']]
    doc['rewrites'] = [Rewrite(**item) for item in doc.get('rewrites', [])]
    return Document(**doc)


def render_page(path, index, scale=1.5, forms=False):
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            if forms: doc.init_forms()
            page = doc[index]
            try:
                bitmap = page.render(scale=scale, may_draw_forms=forms, draw_annots=forms)
                try: return bitmap.to_pil().convert('RGB').copy()
                finally: bitmap.close()
            finally: page.close()
        finally: doc.close()


def baseline_rect(x0, x1, baseline, size=12, height=18, font='Helvetica'):
    offset = height / 2 - FONT_ASCENT.get(font, 718) * size / 2000
    bottom = baseline - offset
    return [x0, bottom, x1, bottom + height]


def overlap(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return width * height


def _detect(page, index):
    """Detect underscore baselines, dates, small square glyphs and blank cells."""
    anchors, boxes, cells = [], [], []
    rows: dict[float, list] = {}
    for c in page.chars:
        if c['text'] == '_':
            baseline = round(float(c['matrix'][5]), 1)
            rows.setdefault(baseline, []).append(c)
        if c['text'] in ('\uf06f', '\u2610', '\u25a1'):
            boxes.append([c['x0'], page.height-c['bottom'], c['x1'], page.height-c['top']])
    for baseline, chars in rows.items():
        chars.sort(key=lambda c:c['x0']); runs=[]
        for char in chars:
            if not runs or char['x0']-runs[-1][-1]['x1']>1.5:
                runs.append([char])
            else: runs[-1].append(char)
        spans=[(r[0]['x0'],r[-1]['x1']) for r in runs if len(r)>=2]
        slash_chars=[c for c in page.chars if c['text']=='/' and abs(float(c['matrix'][5])-baseline)<.6]
        used=set()
        for j in range(len(spans)-2):
            triplet=spans[j:j+3]
            if j in used: continue
            if all(any(a[1]-.2 <= c['x0'] <= b[0]+.2 for c in slash_chars) and b[0]-a[1]<12 for a,b in zip(triplet,triplet[1:])):
                family=f'date_{index+1}_{len(anchors)+1}'
                for offset,part in enumerate(('day','month','year')):
                    left,right=triplet[offset]
                    anchors.append(Anchor(index,left,right,baseline,'date',family,part));used.add(j+offset)
        for j,(left,right) in enumerate(spans):
            if j not in used and right-left>=22:
                anchors.append(Anchor(index,left,right,baseline,'line'))
    try:
        tables=page.find_tables()
        table_cells=list(dict.fromkeys(tuple(c) for t in tables for c in t.cells))
    except Exception:
        table_cells=[]
    # pdfplumber intentionally omits isolated one-cell tables. A standalone
    # outlined response box is still an input candidate, marked for review.
    for rect in page.rects:
        cell=(rect['x0'],rect['top'],rect['x1'],rect['bottom'])
        if not rect.get('fill') and rect['width']>=60 and 22<=rect['height']<=300 and rect['width']*rect['height']<page.width*page.height*.5:
            if not any(max(abs(x-y) for x,y in zip(cell,c))<1 for c in table_cells):table_cells.append(cell)
    for cell in table_cells:
        x0,top,x1,bottom=cell
        if x1-x0<60 or bottom-top<22: continue
        chars=[c for c in page.chars if x0+1<c['x0']<x1-1 and top+1<c['top']<bottom-1]
        if not chars:
            cells.append(([x0+4,page.height-bottom+4,x1-4,page.height-top-4], 'empty table cell'))
        else:
            first=min(c['top'] for c in chars)
            if first-top>=22:
                cells.append(([x0+4,page.height-first+3,x1-4,page.height-top-4], 'space above a table-cell label'))
            elif any(c['text'] in ('\uf06f','\u2610','\u25a1') for c in chars):
                last=max(c['bottom'] for c in chars)
                if bottom-last>=28:
                    cells.append(([x0+4,page.height-bottom+4,x1-4,page.height-last-5], 'response area below choices'))
    # Thin vector rules are supported; exclude table borders and text underlines.
    for edge in page.edges:
        if edge.get('orientation')!='h' or edge['x1']-edge['x0']<30:continue
        top=edge['top'];left=edge['x0'];right=edge['x1']
        if any(abs(top-c[1])<4 or abs(top-c[3])<4 for c in table_cells if min(right,c[2])-max(left,c[0])>20):continue
        if top<30 or top>page.height-35:continue
        if any(c['text'].strip() and c['text']!='_' and left<=c['x0']<=right and -4<top-c['bottom']<7 for c in page.chars):continue
        baseline=page.height-top+1
        if not any(abs(a.baseline-baseline)<4 and abs(a.x0-left)<4 for a in anchors):
            anchors.append(Anchor(index,left,right,baseline,'line'))
    for rect in page.rects:
        width,height=rect['width'],rect['height']
        if 6<=width<=16 and 6<=height<=16 and .8<width/height<1.2:
            box=[rect['x0'],page.height-rect['bottom'],rect['x1'],page.height-rect['top']]
            if not any(overlap(box,b)>min(width*height,(b[2]-b[0])*(b[3]-b[1]))*.5 for b in boxes):boxes.append(box)
    words=page.extract_words()
    labels=[]
    for box in boxes:
        candidates=[w for w in words if w['x0']>=box[2]-.5 and w['x0']-box[2]<65 and abs((page.height-(w['top']+w['bottom'])/2)-(box[1]+box[3])/2)<6]
        label=min(candidates,key=lambda w:w['x0'])['text'] if candidates else ''
        labels.append(re.sub(r'[^a-z]', '',label.lower()))
    return anchors,boxes,labels,cells


def analyze(document: Document, discover: bool | None=None, prefer_template: bool=True, pages: set[int] | None=None):
    """Return an edited copy and an auditable change report; no PDF is written."""
    result=copy.deepcopy(document)
    if result.unsupported:
        raise ValueError('\n'.join(result.unsupported))
    scope=set(range(len(document.sizes))) if pages is None else {i for i in pages if 0 <= i < len(document.sizes)}
    report={'version':VERSION,'source':document.source,'changes':[],'review':[], 'pages':len(scope),'scope_pages':sorted(i+1 for i in scope)}
    if not result.fields and prefer_template and pages is None:
        source=Path(document.source);sibling=source.with_name(source.stem+'_fillable.pdf')
        if sibling.exists() and sibling.resolve()!=source.resolve():
            try:
                matched=transfer_template(source,sibling)
                result.fields=matched.fields;report['template_used']=str(sibling)
                report['changes'].append({'page':1,'field':'matching template','action':f'transfer {len(result.fields)} widgets after verifying every page of source artwork'})
            except ValueError as exc:report['review'].append(f'Sibling template was not used: {exc}')
    if discover is None: discover=not result.fields
    all_anchors=[]; used=set()
    with pdfplumber.open(document.source) as pdf:
        for index,page in enumerate(pdf.pages):
            if index not in scope:continue
            if len(page.chars)<5:
                report['review'].append(f'Page {index+1}: no extractable text; scans need OCR or manual field placement.')
            anchors,boxes,labels,cells=_detect(page,index);all_anchors.extend(anchors)
            existing=[f for f in result.fields if f.page==index]
            for f in list(existing):
                if f.kind not in ('text','choice') or f.multiline or f.locked: continue
                x0,y0,x1,y1=f.rect; center=(y0+y1)/2
                candidates=[]
                for a in anchors:
                    horizontal=max(0,min(x1,a.x1)-max(x0,a.x0))
                    ratio=horizontal/min(x1-x0,a.x1-a.x0) if min(x1-x0,a.x1-a.x0)>0 else 0
                    distance=abs(center-a.baseline)
                    if ratio>.55 and distance<27:
                        candidates.append((distance+abs(x0-a.x0)*.12+(1-ratio)*15,a))
                if not candidates:continue
                candidates.sort(key=lambda pair:pair[0]);a=candidates[0][1]
                if len(candidates)>1 and candidates[1][0]-candidates[0][0]<1 and candidates[1][1].family!=a.family:
                    report['review'].append(f'{f.name}: nearby writing lines are ambiguous; position retained.');continue
                family=[v for v in anchors if a.family and v.family==a.family]
                whole_date=a.kind=='date' and len(family)==3 and x0<family[0].x1 and x1>family[-1].x0
                if whole_date:
                    parsed=re.fullmatch(r'\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\s*',f.value) if f.value else None
                    if f.value and not parsed:
                        report['review'].append(f'{f.name}: existing non-date value retained; date was not split.');continue
                    result.fields.remove(f)
                    for part,anchor in enumerate(family):
                        nf=copy.deepcopy(f);nf.key=uuid.uuid4().hex;nf.name=f'{f.name}_{anchor.part}'
                        nf.max_length=4 if part==2 else 2;nf.value=parsed[part+1].zfill(nf.max_length) if parsed else '';nf.alignment=1
                        nf.rect=baseline_rect(anchor.x0+.4,anchor.x1-.4,anchor.baseline,nf.font_size,max(18,nf.font_size+6),nf.font)
                        nf.tooltip=f'{f.tooltip or f.name}: {anchor.part}'
                        result.fields.append(nf);used.add(id(anchor))
                    report['changes'].append({'page':index+1,'field':f.name,'action':'split date into day/month/year at printed baseline'})
                else:
                    target=a.baseline+(0 if a.kind=='date' else 2)
                    new=baseline_rect(x0,x1,target,f.font_size,max(18,f.font_size+6),f.font)
                    if max(abs(x-y) for x,y in zip(new,f.rect))>.1:
                        report['changes'].append({'page':index+1,'field':f.name,'action':'align text to writing line','before':f.rect.copy(),'after':new})
                        f.rect=new
                    used.add(id(a))
            for f in existing:
                if f.kind not in ('radio','checkbox') or f.locked:continue
                near=[b for b in boxes if abs((b[0]+b[2]-f.rect[0]-f.rect[2])/2)<10 and abs((b[1]+b[3]-f.rect[1]-f.rect[3])/2)<10]
                if near:
                    box=min(near,key=lambda b:sum(abs(x-y) for x,y in zip(b,f.rect)))
                    if max(abs(x-y) for x,y in zip(box,f.rect))>.2:
                        report['changes'].append({'page':index+1,'field':f.name,'action':'align X to printed square','before':f.rect.copy(),'after':box})
                        f.rect=box.copy()
            if not discover:continue
            for a in anchors:
                rect=baseline_rect(a.x0+.4,a.x1-.4,a.baseline+(0 if a.kind=='date' else 2))
                if id(a) in used or any(overlap(rect,f.rect)>min((rect[2]-rect[0])*(rect[3]-rect[1]),(f.rect[2]-f.rect[0])*(f.rect[3]-f.rect[1]))*.35 for f in result.fields if f.page==index):continue
                name=f'auto_p{index+1}_{len(result.fields)+1}_{a.part or "text"}'
                result.fields.append(Field.make(name,index,rect,max_length=(4 if a.part=='year' else 2) if a.kind=='date' else 0,tooltip='Detected '+(a.part or 'writing line'),alignment=1 if a.kind=='date' else 0))
                report['changes'].append({'page':index+1,'field':name,'action':'create field on detected writing line'})
            pending=[]
            for box,label in zip(boxes,labels):
                if any(overlap(box,f.rect)>(box[2]-box[0])*(box[3]-box[1])*.35 for f in result.fields if f.page==index):continue
                f=Field.make(f'auto_p{index+1}_check_{len(result.fields)+len(pending)+1}',index,box,kind='checkbox',tooltip=label)
                pending.append((f,label))
            opposite={'yes':'no','no':'yes','ja':'nein','nein':'ja','male':'female','female':'male'}
            paired=set()
            size_options={'xs','s','m','l','xl','xxl','xxxl'}
            for i,(f,label) in enumerate(pending):
                if label not in size_options or i in paired:continue
                row=[(j,item,text) for j,(item,text) in enumerate(pending)
                     if text in size_options and abs(f.rect[1]-item.rect[1])<6]
                unique={text for _,_,text in row}
                if len(unique)>=3:
                    group=f'auto_p{index+1}_size_{len(result.fields)+i+1}'
                    for _,item,text in row:
                        item.kind='radio';item.group=group;item.name=group;item.option=text.upper()
                    paired.update(j for j,_,_ in row)
            def partner(i):
                if i in paired:return None
                f,label=pending[i];best=[]
                for j,(other,text) in enumerate(pending):
                    if j==i or text!=opposite.get(label):continue
                    dx=abs(f.rect[0]-other.rect[0]);dy=abs(f.rect[1]-other.rect[1])
                    if (dx<20 and dy<42) or (dy<6 and dx<210):best.append((dx+dy*2,j))
                return min(best)[1] if best else None
            for i,(f,label) in enumerate(pending):
                if i in paired:continue
                j=partner(i)
                if j is not None and j not in paired and partner(j)==i:
                    other=pending[j][0];group=f'auto_p{index+1}_choice_{len(result.fields)+i+1}'
                    for item,opt in ((f,label),(other,pending[j][1])):
                        item.kind='radio';item.group=group;item.name=group;item.option=opt.capitalize()
                    paired.update((i,j))
            for f,_ in pending:
                result.fields.append(f);report['changes'].append({'page':index+1,'field':f.name,'action':'create exclusive choice' if f.kind=='radio' else 'create X checkbox'})
            for rect,reason in cells:
                area=(rect[2]-rect[0])*(rect[3]-rect[1])
                if area<=0 or any(overlap(rect,f.rect)>area*.08 for f in result.fields if f.page==index):continue
                name=f'auto_p{index+1}_cell_{len(result.fields)+1}'
                result.fields.append(Field.make(name,index,rect,multiline=rect[3]-rect[1]>32,tooltip=reason))
                report['changes'].append({'page':index+1,'field':name,'action':'create table response field','confidence':'review','reason':reason})
    report['review'].append('Automatic detection is heuristic. Review table fields, grouping and any unmarked areas in the editor before distributing the PDF.')
    for change in report['changes']:
        action=change.get('action','')
        if 'align' in action.lower() or 'split date' in action.lower():
            change.setdefault('confidence','high')
            change.setdefault('reason','Matched the existing field to a detected printed baseline or checkbox square.')
        elif 'matching template' in change.get('field','').lower():
            change.setdefault('confidence','high')
            change.setdefault('reason','Every source page was verified against the selected template.')
        else:
            change.setdefault('confidence','review')
            change.setdefault('reason','Automatic detection found a likely answer area; confirm its label and position before export.')
    report['field_widgets']=len(result.fields)
    return result,report


def validate_document(doc):
    if doc.unsupported:raise ValueError('\n'.join(doc.unsupported))
    seen={};radio={}
    for f in doc.fields:
        if not f.name.strip():raise ValueError('Every field needs a name.')
        if f.kind=='radio':
            if not f.group.strip():raise ValueError('Radio choices need a group name.')
            radio.setdefault(f.group,[]).append(f)
        elif f.name in seen:raise ValueError(f'Duplicate field name: {f.name}')
        else:seen[f.name]=f
        if f.page<0 or f.page>=len(doc.sizes):raise ValueError(f'{f.name}: invalid page.')
        x0,y0,x1,y1=f.rect;pw,ph=doc.sizes[f.page]
        if not all(math.isfinite(v) for v in f.rect) or x1-x0<3 or y1-y0<3 or x0<-.1 or y0<-.1 or x1>pw+.1 or y1>ph+.1:
            raise ValueError(f'{f.name}: field is outside its page or too small.')
        if not 1<=f.font_size<=100:raise ValueError(f'{f.name}: font size must be 1-100 points.')
        if f.max_length and len(f.value)>f.max_length:raise ValueError(f'{f.name}: value exceeds its character limit.')
        for color in (f.text_color,f.background,f.border_color,f.highlight):
            if color is not None and not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError(f'{f.name}: invalid color {color}.')
        try:f.value.encode('cp1252')
        except UnicodeEncodeError:raise ValueError(f'{f.name}: this version supports Latin/Western European PDF entry text; an embedded Unicode font is needed for this value.')
    field_keys={f.key:f for f in doc.fields}
    for f in doc.fields:
        if not isinstance(f.linked_fields,list) or len(set(f.linked_fields))!=len(f.linked_fields):raise ValueError(f'{f.name}: invalid linked fields.')
        for key in f.linked_fields:
            linked=field_keys.get(key)
            if linked is None or linked.key==f.key or linked.kind not in ('text','choice'):
                raise ValueError(f'{f.name}: links must point to a different text field or dropdown in this PDF.')
    rewrite_keys=set()
    for r in doc.rewrites:
        if r.key in rewrite_keys:raise ValueError('Duplicate rewrite marker key.')
        rewrite_keys.add(r.key)
        if r.page<0 or r.page>=len(doc.sizes):raise ValueError('A text correction points to an invalid page.')
        x0,y0,x1,y1=r.rect;pw,ph=doc.sizes[r.page]
        if not all(math.isfinite(v) for v in r.rect) or x1-x0<3 or y1-y0<3 or x0<-.1 or y0<-.1 or x1>pw+.1 or y1>ph+.1:
            raise ValueError('A text correction is outside its page or too small.')
        if not 1<=r.font_size<=100:raise ValueError('Text correction size must be 1-100 points.')
        if r.font not in ('Helvetica','Times-Roman','Courier'):raise ValueError('Unsupported text correction font.')
        for color in (r.text_color,r.fill):
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Text correction colors must be six-digit hex colors.')
        try:r.text.encode('cp1252')
        except UnicodeEncodeError:raise ValueError('Text correction uses unsupported characters; enter Western European text.')
    for name,options in radio.items():
        if name in seen:raise ValueError(f'Radio group {name} conflicts with another field name.')
        if len({f.option for f in options})!=len(options):raise ValueError(f'Radio group {name} has duplicate option values.')
        if any(not f.option or f.option=='Off' for f in options):raise ValueError(f'Radio group {name} needs non-empty option values other than Off.')
        if sum(f.checked for f in options)>1:raise ValueError(f'Radio group {name} has multiple selected options.')


def _arr(vals):return ArrayObject([FloatObject(v) for v in vals])


def _button_appearance(writer,f,on):
    width=f.rect[2]-f.rect[0];height=f.rect[3]-f.rect[1]
    s=['q']
    if f.background:
        s.append(' '.join(map(str,rgb(f.background)))+f' rg 0 0 {width} {height} re f')
    if f.border_width:
        inset=f.border_width/2
        s.append(' '.join(map(str,rgb(f.border_color)))+f' RG {f.border_width} w {inset} {inset} {width-2*inset} {height-2*inset} re S')
    if on:
        mark=min(width,height);cx,cy=width/2,height/2
        color=' '.join(map(str,rgb(f.text_color)))
        if f.kind=='radio':
            radius=mark*.22
            k=radius*.55228475
            s.append(f'{color} rg {cx+radius} {cy} m {cx+radius} {cy+k} {cx+k} {cy+radius} {cx} {cy+radius} c {cx-k} {cy+radius} {cx-radius} {cy+k} {cx-radius} {cy} c {cx-radius} {cy-k} {cx-k} {cy-radius} {cx} {cy-radius} c {cx+k} {cy-radius} {cx+radius} {cy-k} {cx+radius} {cy} c f')
        else:
            inset=mark*.28;stroke=max(.7,min(1.6,mark*.12))
            s.append(f'{color} RG {stroke} w 1 J {inset} {inset} m {width-inset} {height-inset} l S {inset} {height-inset} m {width-inset} {inset} l S')
    s.append('Q');ap=DecodedStreamObject();ap.set_data('\n'.join(s).encode('ascii'))
    ap.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):_arr([0,0,width,height]),NameObject('/Resources'):DictionaryObject()})
    return writer._add_object(ap)


def export_pdf(document: Document, output: str | Path, sample=False):
    """Rebuild supported controls with canonical shared field/widget references."""
    document=copy.deepcopy(document)
    output=Path(output).resolve();source=Path(document.source).resolve()
    if output==source:raise ValueError('Choose a new output filename; the source PDF is preserved.')
    if digest(source)!=document.sha256:raise ValueError('The source PDF changed. Reopen it before exporting.')
    if sample:
        chosen=set()
        for f in document.fields:
            if f.kind=='radio' and f.group not in chosen:
                if any(o.checked for o in document.fields if o.group==f.group):chosen.add(f.group)
                else:f.checked=True;chosen.add(f.group)
            elif f.kind=='checkbox':f.checked=True
            elif f.kind in ('text','choice') and not f.value:
                if f.kind=='choice':f.value=f.choices[0] if f.choices else ''
                elif f.name.endswith('_day'):f.value='14'
                elif f.name.endswith('_month'):f.value='09'
                elif f.name.endswith('_year'):f.value='2027'
                elif any(x in (f.name+' '+f.tooltip).lower() for x in ('date','datum','birth','geburt')):f.value='14/09/2027'
                else:f.value='Alex Taylor' if any(x in (f.name+' '+f.tooltip).lower() for x in ('name','signature')) else 'Sample text\nSecond line' if f.multiline else 'Sample text'
                if f.max_length:f.value=f.value[:f.max_length]
    validate_document(document)
    reader=PdfReader(source);writer=PdfWriter();writer.clone_document_from_reader(reader)
    for page in writer.pages:
        page[NameObject('/Annots')]=ArrayObject([r for r in page.get('/Annots',[]) if r.get_object().get('/Subtype')!='/Widget'])
    fonts=DictionaryObject()
    for key,font in (('/Helv','Helvetica'),('/TiRo','Times-Roman'),('/Cour','Courier'),('/FStudioHelv','Helvetica'),('/FStudioTiRo','Times-Roman'),('/FStudioCour','Courier')):
        fonts[NameObject(key)]=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/'+font),NameObject('/Encoding'):NameObject('/WinAnsiEncoding')}))
    for index,page in enumerate(writer.pages):
        changes=[r for r in document.rewrites if r.page==index]
        if not changes:continue
        resources=page.get('/Resources',DictionaryObject())
        if hasattr(resources,'get_object'):resources=resources.get_object()
        resources=DictionaryObject(dict(resources))
        page_fonts=resources.get('/Font',DictionaryObject())
        if hasattr(page_fonts,'get_object'):page_fonts=page_fonts.get_object()
        page_fonts=DictionaryObject(dict(page_fonts))
        for font_name in ('/FStudioHelv','/FStudioTiRo','/FStudioCour'):
            page_fonts[NameObject(font_name)]=fonts[NameObject(font_name)]
        resources[NameObject('/Font')]=page_fonts
        page[NameObject('/Resources')]=resources
        commands=[]
        for r in changes:
            x0,y0,x1,y1=r.rect;width=x1-x0;height=y1-y0
            font_key={'Helvetica':'/FStudioHelv','Times-Roman':'/FStudioTiRo','Courier':'/FStudioCour'}[r.font]
            commands.extend(['q',f'{" ".join(map(str,rgb(r.fill)))} rg {x0} {y0} {width} {height} re f',f'{x0} {y0} {width} {height} re W n'])
            baseline=y0+max(1,(height-FONT_ASCENT[r.font]*r.font_size/1000)/2)
            commands.extend(['BT',f'{font_key} {r.font_size} Tf',f'{" ".join(map(str,rgb(r.text_color)))} rg'])
            for line_index,line in enumerate(r.text.splitlines() or ['']):
                encoded=line.encode('cp1252').hex().upper()
                line_y=baseline-line_index*r.font_size*1.2
                commands.extend([f'1 0 0 1 {x0+2} {line_y} Tm',f'<{encoded}> Tj'])
            commands.extend(['ET','Q'])
        stream=DecodedStreamObject();stream.set_data(('\n'.join(commands)+'\n').encode('ascii'));ref=writer._add_object(stream)
        contents=page.get('/Contents')
        refs=list(contents) if isinstance(contents,ArrayObject) else [contents] if contents else []
        page[NameObject('/Contents')]=ArrayObject([*refs,ref])
    roots=ArrayObject();acro=DictionaryObject({NameObject('/Fields'):roots,NameObject('/DR'):DictionaryObject({NameObject('/Font'):fonts}),NameObject('/DA'):TextStringObject('/Helv 12 Tf 0 g'),NameObject('/NeedAppearances'):BooleanObject(False)})
    writer._root_object[NameObject('/AcroForm')]=writer._add_object(acro)
    radio_parents={};values={};expected={}
    for f in document.fields:
        if f.kind=='radio' and f.group not in radio_parents:
            active=next((o.option for o in document.fields if o.kind=='radio' and o.group==f.group and o.checked),'Off')
            parent=DictionaryObject({NameObject('/FT'):NameObject('/Btn'),NameObject('/Ff'):NumberObject(32768),NameObject('/T'):TextStringObject(f.group),NameObject('/V'):NameObject('/'+active),NameObject('/Kids'):ArrayObject()})
            ref=writer._add_object(parent);radio_parents[f.group]=ref;roots.append(ref);expected[f.group]='/'+active
        page=writer.pages[f.page]
        obj=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Widget'),NameObject('/Rect'):_arr(f.rect),NameObject('/F'):NumberObject(4),NameObject('/P'):page.indirect_reference,NameObject('/TU'):TextStringObject(f.tooltip or f.name)})
        mk=DictionaryObject({NameObject('/BC'):_arr(rgb(f.border_color))})
        if f.background:mk[NameObject('/BG')]=_arr(rgb(f.background))
        obj[NameObject('/MK')]=mk
        obj[NameObject('/BS')]=DictionaryObject({NameObject('/W'):FloatObject(f.border_width),NameObject('/S'):NameObject('/S')})
        if f.kind in ('text','choice'):
            obj[NameObject('/T')]=TextStringObject(f.name)
            obj[NameObject('/FT')]=NameObject('/Ch' if f.kind=='choice' else '/Tx')
            obj[NameObject('/V')]=TextStringObject(f.value);obj[NameObject('/DV')]=TextStringObject('')
            obj[NameObject('/Ff')]=NumberObject(131072 if f.kind=='choice' else 4096 if f.multiline else 0)
            obj[NameObject('/Q')]=NumberObject(f.alignment)
            fontid={'Helvetica':'/Helv','Times-Roman':'/TiRo','Courier':'/Cour'}.get(f.font,'/Helv')
            obj[NameObject('/DA')]=TextStringObject(f'{fontid} {f.font_size} Tf '+ ' '.join(map(str,rgb(f.text_color)))+' rg')
            if f.max_length:obj[NameObject('/MaxLen')]=NumberObject(f.max_length)
            if f.kind=='choice':obj[NameObject('/Opt')]=ArrayObject([TextStringObject(v) for v in f.choices])
            ref=writer._add_object(obj);roots.append(ref);values[f.name]=f.value;expected[f.name]=f.value
        else:
            state=f.option if f.checked else 'Off'
            obj[NameObject('/AP')]=DictionaryObject({NameObject('/N'):DictionaryObject({NameObject('/Off'):_button_appearance(writer,f,False),NameObject('/'+f.option):_button_appearance(writer,f,True)})})
            obj[NameObject('/AS')]=NameObject('/'+state)
            if f.kind=='radio':
                obj[NameObject('/Parent')]=radio_parents[f.group]
                ref=writer._add_object(obj);radio_parents[f.group].get_object()['/Kids'].append(ref)
            else:
                obj[NameObject('/FT')]=NameObject('/Btn');obj[NameObject('/T')]=TextStringObject(f.name);obj[NameObject('/V')]=NameObject('/'+state)
                ref=writer._add_object(obj);roots.append(ref);expected[f.name]='/'+state
        page['/Annots'].append(ref)
    if values:writer.update_page_form_field_values(None,values,auto_regenerate=False)
    # pypdf generates the text stream but does not paint /MK background/border
    # colors. Paint those inside the appearance as well as declaring /MK, so
    # saved PDFs render consistently before and after a reader edits a value.
    by_name={f.name:f for f in document.fields if f.kind in ('text','choice')}
    for page in writer.pages:
        for ref in page.get('/Annots',[]):
            obj=ref.get_object();f=by_name.get(str(obj.get('/T','')))
            if f is None:continue
            width,height=f.rect[2]-f.rect[0],f.rect[3]-f.rect[1];paint=['q']
            if f.background:paint.append(' '.join(map(str,rgb(f.background)))+f' rg 0 0 {width} {height} re f')
            if f.border_width:
                inset=f.border_width/2
                paint.append(' '.join(map(str,rgb(f.border_color)))+f' RG {f.border_width} w {inset} {inset} {width-2*inset} {height-2*inset} re S')
            paint.append('Q')
            ap=obj['/AP']['/N'].get_object();ap.set_data(('\n'.join(paint)+'\n').encode('ascii')+ap.get_data())
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_name(output.stem+'.writing.pdf')
    try:
        with temp.open('wb') as stream:writer.write(stream)
        verified=PdfReader(temp);actual=verified.get_fields() or {}
        if set(actual)!=set(expected):raise RuntimeError('Export field tree does not match the editor.')
        if any(str(actual[k].get('/V',''))!=str(v) for k,v in expected.items()):raise RuntimeError('Exported field values failed the save/reopen check.')
        count=0
        for p in verified.pages:
            for ref in p.get('/Annots',[]):
                o=ref.get_object()
                if o.get('/Subtype')!='/Widget':continue
                count+=1
                if not o.get('/AP',{}).get('/N'):raise RuntimeError('An exported widget has no appearance.')
                name=qualified(o)
                if str(inherited(o,'/V',''))!=str(expected[name]):raise RuntimeError('Widget value and canonical field value disagree.')
        if count!=len(document.fields):raise RuntimeError('Export widget count changed unexpectedly.')
        for index,(p,q) in enumerate(zip(reader.pages,verified.pages)):
            a=p.get_contents();b=q.get_contents()
            if not any(r.page==index for r in document.rewrites) and (a.get_data() if a else b'')!=(b.get_data() if b else b''):
                raise RuntimeError('Source page artwork changed during export.')
        temp.replace(output)
    finally:
        if temp.exists():temp.unlink()
    return {'pages':len(verified.pages),'fields':len(actual),'widgets':count,'output':str(output),'values_verified':True,'source_artwork_preserved':not bool(document.rewrites),'rewritten_areas':len(document.rewrites)}


def transfer_template(source_path,template_path):
    source=load_document(source_path);template=load_document(template_path)
    if source.fields:raise ValueError('The input already has fields; open it directly instead of transferring a template.')
    if len(source.sizes)!=len(template.sizes):raise ValueError('Template page count differs. Use automatic detection and manual review for this new layout.')
    with pdfplumber.open(source.source) as a,pdfplumber.open(template.source) as b:
        for i,(p,q) in enumerate(zip(a.pages,b.pages)):
            def fingerprint(page):return [(c['text'],round(c['x0'],1),round(c['top'],1)) for c in page.chars]
            if source.sizes[i]!=template.sizes[i] or fingerprint(p)!=fingerprint(q):
                raise ValueError(f'Page {i+1} does not match the template artwork. Field transfer stopped to avoid misplaced controls.')
    source.fields=copy.deepcopy(template.fields)
    return source
