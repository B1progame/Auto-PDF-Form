from pathlib import Path
import copy
import sys
import pytest
from reportlab.pdfgen import canvas
from pypdf import PdfReader
from pypdf.generic import ContentStream

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import Field,Rewrite,load_document,analyze,export_pdf,baseline_rect,render_page,save_project,load_project,transfer_template


@pytest.fixture
def source(tmp_path):
    p=tmp_path/'form.pdf';c=canvas.Canvas(str(p),pagesize=(600,800))
    c.setFont('Helvetica',11)
    c.drawString(60,700,'Student: __________________________')
    c.drawString(60,650,'Date: _____/_____/_________')
    c.rect(60,590,10,10);c.drawString(77,590,'yes / ja')
    c.rect(160,590,10,10);c.drawString(177,590,'no / nein')
    c.rect(260,440,230,70);c.drawString(60,470,'Details')
    c.save();return p


def test_discovery_dates_groups_and_sample_roundtrip(source,tmp_path):
    doc,report=analyze(load_document(source))
    dates=[f for f in doc.fields if f.max_length in (2,4)]
    assert len(dates)==3 and [f.max_length for f in dates]==[2,2,4]
    radios=[f for f in doc.fields if f.kind=='radio']
    assert len(radios)==2 and radios[0].group==radios[1].group
    assert any(f.multiline for f in doc.fields)
    out=tmp_path/'sample.pdf';result=export_pdf(doc,out,sample=True)
    assert result['values_verified'] and result['source_artwork_preserved']
    r=PdfReader(out);group=r.get_fields()[radios[0].group]
    assert sum(k.get_object()['/AS']!='/Off' for k in group['/Kids'])==1
    reopened=load_document(out)
    assert not reopened.unsupported
    assert len(reopened.fields)==len(doc.fields)


def test_misalignment_fixed_at_actual_baseline(source,tmp_path):
    doc=load_document(source)
    doc.fields=[Field.make('student_name',0,[105,680,280,698],value='Alex Taylor'),Field.make('date',0,[86,660,190,678],value='14/09/2027')]
    repaired,report=analyze(doc,False)
    assert len(repaired.fields)==4
    name=next(f for f in repaired.fields if f.name=='student_name')
    assert name.rect[1]>doc.fields[0].rect[1]
    out=tmp_path/'fixed.pdf';export_pdf(repaired,out)
    r=PdfReader(out)
    assert r.get_fields()['date_day']['/V']=='14'
    assert r.get_fields()['date_month']['/V']=='09'
    assert r.get_fields()['date_year']['/V']=='2027'
    widget=next(a.get_object() for a in r.pages[0]['/Annots'] if a.get_object().get('/T')=='student_name')
    td=next(v for v,op in ContentStream(widget['/AP']['/N'].get_object(),r).operations if op==b'Td')
    assert abs(float(widget['/Rect'][1])+float(td[1])-702)<.05


def test_non_date_content_is_never_discarded(source):
    doc=load_document(source);doc.fields=[Field.make('date',0,[85,640,200,658],value='Keep this')]
    repaired,report=analyze(doc,False)
    assert len(repaired.fields)==1 and repaired.fields[0].value=='Keep this'
    assert any('non-date' in s for s in report['review'])


def test_project_roundtrip_and_source_change(source,tmp_path):
    doc,_=analyze(load_document(source));p=tmp_path/'project.formstudio.json'
    if len(doc.fields)>1:doc.fields[0].linked_fields=[doc.fields[1].key]
    doc.rewrites=[Rewrite.make(0,[55,685,240,715],text='Corrected text',font='Times-Roman')]
    doc.fields[0].highlight='#ff88aa';save_project(doc,p)
    loaded=load_project(p);assert loaded.fields==doc.fields and loaded.rewrites==doc.rewrites
    source.write_bytes(source.read_bytes()+b'\n% changed')
    with pytest.raises(ValueError,match='changed'):load_project(p)


def test_colors_visible_and_source_artwork_preserved(source,tmp_path):
    doc=load_document(source);doc.fields=[Field.make('color',0,[300,550,470,580],background='#44aa88',border_width=1)]
    out=tmp_path/'colors.pdf';export_pdf(doc,out)
    im=render_page(out,0,1,True)
    pixel=im.getpixel((350,800-565))
    assert max(abs(a-b) for a,b in zip(pixel,(68,170,136)))<4
    assert PdfReader(out).pages[0].get_contents().get_data()==PdfReader(source).pages[0].get_contents().get_data()


def test_validation_rejects_conflicts_and_outside_page(source,tmp_path):
    doc=load_document(source);doc.fields=[Field.make('a',0,[20,20,50,40]),Field.make('a',0,[60,20,90,40])]
    with pytest.raises(ValueError,match='Duplicate'):export_pdf(doc,tmp_path/'bad.pdf')
    doc.fields=doc.fields[:1];doc.fields[0].rect=[-2,0,30,20]
    with pytest.raises(ValueError,match='outside'):export_pdf(doc,tmp_path/'bad.pdf')
    doc.fields=[Field.make('g',0,[20,20,30,30],kind='radio',group='g',option='A',checked=True),Field.make('g',0,[60,20,70,30],kind='radio',group='g',option='B',checked=True)]
    with pytest.raises(ValueError,match='multiple selected'):export_pdf(doc,tmp_path/'bad.pdf')
    with pytest.raises(ValueError,match='new output'):export_pdf(doc,source)


def test_strict_template_refuses_different_artwork(source,tmp_path):
    doc,_=analyze(load_document(source));template=tmp_path/'template.pdf';export_pdf(doc,template)
    transferred=transfer_template(source,template);assert len(transferred.fields)==len(doc.fields)
    wrong=tmp_path/'wrong.pdf';c=canvas.Canvas(str(wrong),pagesize=(600,800));c.drawString(50,700,'Different');c.save()
    with pytest.raises(ValueError,match='does not match'):transfer_template(wrong,template)


def test_second_automatic_pass_does_not_duplicate_fields(source,tmp_path):
    first,_=analyze(load_document(source));out=tmp_path/'first.pdf';export_pdf(first,out)
    second,_=analyze(load_document(out))
    assert len(first.fields)==len(second.fields)
    assert {f.name for f in first.fields}=={f.name for f in second.fields}


def test_unicode_value_rejected_instead_of_silent_loss(source,tmp_path):
    doc=load_document(source);doc.fields=[Field.make('name',0,[40,40,200,60],value='\u65e5\u672c')]
    with pytest.raises(ValueError,match='Unicode'):export_pdf(doc,tmp_path/'unicode.pdf')


def test_matching_sibling_template_is_used_without_hardcoded_pages(source,tmp_path):
    doc,_=analyze(load_document(source),prefer_template=False)
    export_pdf(doc,source.with_name(source.stem+'_fillable.pdf'))
    matched,report=analyze(load_document(source))
    assert report.get('template_used')
    assert len(matched.fields)==len(doc.fields)


def test_page_scoped_analysis_does_not_touch_other_pages(tmp_path):
    p=tmp_path/'two-pages.pdf';c=canvas.Canvas(str(p),pagesize=(600,800))
    c.drawString(60,700,'Page one: __________________');c.showPage()
    c.drawString(60,700,'Page two: __________________');c.save()
    doc=load_document(p)
    field=Field.make('page_two',1,[100,680,300,700]);doc.fields=[field]
    scoped,report=analyze(doc,False,pages={0})
    assert scoped.fields[0].rect==field.rect
    assert report['scope_pages']==[1]
    assert report['pages']==1


def test_locked_fields_are_not_automatically_repositioned(source):
    doc=load_document(source)
    locked=Field.make('locked_name',0,[105,680,280,698],value='Keep this',locked=True)
    doc.fields=[locked]
    repaired,report=analyze(doc,False)
    assert repaired.fields[0].rect==locked.rect
    assert repaired.fields[0].value=='Keep this'
    assert not any(change.get('field')=='locked_name' for change in report['changes'])


def test_clothing_sizes_are_detected_as_one_exclusive_group(tmp_path):
    p=tmp_path/'sizes.pdf';c=canvas.Canvas(str(p),pagesize=(600,800))
    for x,label in zip((45,115,185,255,325,395,465),('XS','S','M','L','XL','XXL','XXXL')):
        c.rect(x,500,10,10);c.drawString(x+15,500,label)
    c.save()
    doc,report=analyze(load_document(p),prefer_template=False)
    options=[f for f in doc.fields if f.kind=='radio']
    assert len(options)==7
    assert len({f.group for f in options})==1
    assert {f.option for f in options}=={'XS','S','M','L','XL','XXL','XXXL'}
    assert all(change['confidence']=='review' for change in report['changes'])


def test_table_borders_do_not_pull_existing_fields_into_other_rows(tmp_path):
    p=tmp_path/'table.pdf';c=canvas.Canvas(str(p),pagesize=(600,800))
    for y in (400,450):c.rect(250,y,200,50)
    c.drawString(255,410,'Phone');c.drawString(255,460,'Email');c.save()
    doc=load_document(p);f=Field.make('phone',0,[254,425,446,445]);doc.fields=[f]
    result,report=analyze(doc,False)
    assert result.fields[0].rect==f.rect


def test_german_text_survives_roundtrip(source,tmp_path):
    doc=load_document(source);doc.fields=[Field.make('name',0,[50,50,300,75],value='Müller-Schröder')]
    out=tmp_path/'umlauts.pdf';export_pdf(doc,out)
    assert PdfReader(out).get_fields()['name']['/V']=='Müller-Schröder'
    assert render_page(out,0,.5,True).size==(300,400)


def test_text_correction_is_clipped_font_aware_and_keeps_source_untouched(source,tmp_path):
    doc=load_document(source)
    doc.rewrites=[Rewrite.make(0,[55,685,240,715],text='Corrected line\nSecond line',font='Times-Roman',font_size=12,fill='#ffffff')]
    original=source.read_bytes();out=tmp_path/'corrected-copy.pdf'
    result=export_pdf(doc,out)
    assert source.read_bytes()==original
    assert result['rewritten_areas']==1 and not result['source_artwork_preserved']
    reader=PdfReader(out)
    assert 'Corrected line' in reader.pages[0].extract_text()
    assert 'Second line' in reader.pages[0].extract_text()
    resources=reader.pages[0]['/Resources']['/Font']
    assert resources['/FStudioTiRo'].get_object()['/BaseFont']=='/Times-Roman'
    image=render_page(out,0,1,False)
    assert image.getpixel((210,100))==(255,255,255)


def test_radio_marker_is_round_and_checkbox_marker_is_a_centered_cross(source,tmp_path):
    doc=load_document(source)
    doc.fields=[
        Field.make('exclusive',0,[60,590,76,606],kind='radio',group='exclusive',option='Yes',checked=True),
        Field.make('agree',0,[100,590,116,606],kind='checkbox',checked=True),
    ]
    out=tmp_path/'markers.pdf';export_pdf(doc,out)
    reader=PdfReader(out)
    annotations=[ref.get_object() for ref in reader.pages[0]['/Annots']]
    radio=next(item for item in annotations if item.get('/Parent') and str(item['/Parent'].get_object().get('/T'))=='exclusive')['/AP']['/N']['/Yes'].get_object().get_data()
    checkbox=next(item for item in annotations if str(item.get('/T'))=='agree')['/AP']['/N']['/Yes'].get_object().get_data()
    assert b' c ' in radio and b' l S' not in radio
    assert b' l S' in checkbox
