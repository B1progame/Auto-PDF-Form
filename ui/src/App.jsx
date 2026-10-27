import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlignCenter, AlignHorizontalDistributeCenter, AlignLeft, AlignRight, ArrowDownToLine,
  Check, ChevronDown, ChevronRight,
  CircleHelp, Copy, FilePlus2, FileText, Filter, Focus, FormInput, Grid2X2,
  Layers2, LockKeyhole, Maximize2, MousePointer2, PanelLeftClose, PanelLeftOpen,
  Plus, RotateCcw, RotateCw, Search, Settings2, ShieldCheck, Sparkles, Square,
  TextCursorInput, Trash2, UnlockKeyhole, Upload, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import './App.css'

const typeLabel = { text: 'Text field', choice: 'Dropdown', checkbox: 'Checkbox', radio: 'Radio option', rewrite: 'Printed text correction' }
const shortType = { text: 'Text', choice: 'Dropdown', checkbox: 'Checkbox', radio: 'Radio' }

function iconFor(kind) {
  if (kind === 'checkbox') return <Square size={15} />
  if (kind === 'radio') return <span className="radioGlyph" />
  if (kind === 'choice') return <ChevronDown size={15} />
  return <TextCursorInput size={15} />
}

function Callout({ icon: Icon = CircleHelp, title, children }) {
  return <div className="callout"><Icon size={16} /><div><strong>{title}</strong><p>{children}</p></div></div>
}

function App() {
  const [backend, setBackend] = useState(null)
  const [state, setState] = useState({ pages: [], fields: [], rewrites: [], page: 0, busy: false, dirty: false })
  const [pageImage, setPageImage] = useState(null)
  const [thumbnails, setThumbnails] = useState({})
  const [selected, setSelected] = useState([])
  const [activeTab, setActiveTab] = useState('pages')
  const [activePanel, setActivePanel] = useState('content')
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [allPages, setAllPages] = useState(false)
  const [mode, setMode] = useState('layout')
  const [zoom, setZoom] = useState(100)
  const [toast, setToast] = useState('')
  const [drawer, setDrawer] = useState('')
  const [autoScope, setAutoScope] = useState('all')
  const [autoIntent, setAutoIntent] = useState('find')
  const [drafts, setDrafts] = useState({})
  const [dragPreview, setDragPreview] = useState(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const scrollArea = useRef(null)
  const thumbRequested = useRef(new Set())
  const stateRef = useRef(state)
  const channelTimer = useRef(null)
  const channelConnected = useRef(false)
  const toastTimer = useRef(null)

  const notify = useCallback((message) => {
    if (!message) return
    setToast(message)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 4200)
  }, [])

  useEffect(() => {
    let disposed = false
    function ready() {
      if (disposed || channelConnected.current) return
      if (!window.qt?.webChannelTransport || !window.QWebChannel) {
        channelTimer.current = window.setTimeout(ready, 80)
        return
      }
      channelConnected.current = true
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
        const api = channel.objects.pdfStudio
        window.__pdfStudioBackend = api
        window.__pdfStudioReady = true
        setBackend(api)
        try { stateRef.current = JSON.parse(api.getState()); setState(stateRef.current) } catch { /* first load is empty */ }
        api.event.connect((raw) => {
          let event
          try { event = JSON.parse(raw) } catch { return }
          if (event.type === 'state') { stateRef.current = event.state; setState(event.state) }
          if (event.type === 'page') {
            if (event.page === stateRef.current.page) setPageImage({ source: stateRef.current.source, page: event.page, image: event.image })
          }
          if (event.type === 'thumbnail') setThumbnails((old) => ({ ...old, [event.page]: event.image }))
          if (event.type === 'analysis') setDrawer('review')
          if (event.type === 'selectField') setSelected([event.key])
          if (event.type === 'selectRewrite') setSelected([event.key])
          if (event.type === 'notice') notify(event.message)
          if (event.type === 'error' || event.type === 'warning') notify(event.message)
        })
      })
    }
    ready()
    return () => { disposed = true; window.clearTimeout(channelTimer.current); channelConnected.current = false; delete window.__pdfStudioReady; delete window.__pdfStudioBackend }
  }, [notify])

  useEffect(() => {
    if (backend && state.source) backend.requestPage(state.page, 'ui')
  }, [backend, state.page, state.source, state.preview])

  useEffect(() => {
    if (!backend || !state.pages.length) return
    state.pages.forEach((page) => {
      if (thumbRequested.current.has(page.index)) return
      thumbRequested.current.add(page.index)
      backend.requestThumbnail(page.index)
    })
  }, [backend, state.pages])

  const allItems = useMemo(() => [...state.fields, ...(state.rewrites || []).map((item) => ({ ...item, kind: 'rewrite', name: `Correction · ${item.text || 'new text'}`, tooltip: 'Cover and replace printed page text' }))], [state.fields, state.rewrites])
  const current = allItems.find((field) => selected.includes(field.key)) || null
  const shownFields = useMemo(() => allItems.filter((field) => {
    if (!allPages && field.page !== state.page) return false
    if (kindFilter !== 'all' && field.kind !== kindFilter) return false
    const q = query.trim().toLocaleLowerCase()
    if (q && ![field.name, field.tooltip, field.group, field.option].some((value) => String(value || '').toLocaleLowerCase().includes(q))) return false
    return true
  }), [allItems, state.page, allPages, kindFilter, query])

  const setField = useCallback((field, patch) => {
    if (!backend || !field) return
    if (field.kind === 'rewrite') backend.setRewrite(field.key, JSON.stringify(patch))
    else backend.setField(field.key, JSON.stringify(patch))
  }, [backend])

  function selectField(field, additive = false) {
    if (field.page !== state.page) backend?.setPage(field.page)
    setSelected((old) => additive ? (old.includes(field.key) ? old.filter((key) => key !== field.key) : [...old, field.key]) : [field.key])
  }

  function changePage(page) {
    if (page < 0 || page >= state.pages.length) return
    setSelected([])
    backend?.setPage(page)
    if (scrollArea.current) scrollArea.current.scrollTop = 0
  }

  function startGesture(event, field, resize = false) {
    if (mode !== 'layout' || state.preview || field.locked || event.button !== 0) return
    event.preventDefault(); event.stopPropagation()
    const additive = event.shiftKey || event.ctrlKey || event.metaKey
    let chosen = selected
    if (additive) chosen = chosen.includes(field.key) ? chosen.filter((key) => key !== field.key) : [...chosen, field.key]
    else if (!chosen.includes(field.key)) chosen = [field.key]
    if (!chosen.length) return
    setSelected(chosen)
    const frame = event.currentTarget.closest('.pageFrame')?.getBoundingClientRect()
    if (!frame) return
    const originals = allItems.filter((item) => chosen.includes(item.key) && !item.locked).map((item) => ({ key: item.key, rect: [...item.rect] }))
    if (!originals.length) return
    const gesture = { startX: event.clientX, startY: event.clientY, frame, originals, resize: resize ? field.key : null, direction: resize || 'move' }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    let finalRects = null
    function onMove(moveEvent) {
      const dx = (moveEvent.clientX - gesture.startX) / frame.width * state.pages[state.page].width
      const dy = (moveEvent.clientY - gesture.startY) / frame.height * state.pages[state.page].height
      const rects = originals.map(({ key, rect }) => {
        if (gesture.resize && key !== gesture.resize) return { key, rect }
        let next = [...rect]
        if (gesture.direction === 'move') next = [rect[0] + dx, rect[1] - dy, rect[2] + dx, rect[3] - dy]
        else {
          const d = gesture.direction
          if (d.includes('w')) next[0] = rect[0] + dx
          if (d.includes('e')) next[2] = rect[2] + dx
          if (d.includes('n')) next[3] = rect[3] - dy
          if (d.includes('s')) next[1] = rect[1] - dy
        }
        return { key, rect: next }
      })
      finalRects = rects
      setDragPreview(rects)
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      setDragPreview(null)
      if (finalRects) backend?.setFieldBatch(JSON.stringify(finalRects))
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp, { once: true })
  }

  const keyDown = useCallback((event) => {
    const target = event.target
    const typing = target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    if (typing) return
    const cmd = event.ctrlKey || event.metaKey
    if (cmd && event.key.toLowerCase() === 'o') { event.preventDefault(); backend?.openDialog(); return }
    if (cmd && event.key.toLowerCase() === 's') { event.preventDefault(); if (event.shiftKey) backend?.exportPDF(); else backend?.saveProject(); return }
    if (cmd && event.key.toLowerCase() === 'z') { event.preventDefault(); if (event.shiftKey) backend?.redo(); else backend?.undo(); return }
    if (cmd && event.key.toLowerCase() === 'y') { event.preventDefault(); backend?.redo(); return }
    if (cmd && event.key.toLowerCase() === 'd' && current) { event.preventDefault(); backend?.duplicateField(current.key); return }
    if ((event.key === 'Delete' || event.key === 'Backspace') && selected.length && mode === 'layout') {
      event.preventDefault()
      if (window.confirm('Delete ' + selected.length + ' selected field' + (selected.length === 1 ? '' : 's') + '?')) { backend?.deleteFields(JSON.stringify(selected)); setSelected([]) }
      return
    }
    const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }
    if (moves[event.key] && selected.length && mode === 'layout') {
      event.preventDefault(); const amount = event.shiftKey ? 10 : 1; backend?.moveFields(JSON.stringify(selected), moves[event.key][0] * amount, moves[event.key][1] * amount)
    }
  }, [backend, current, mode, selected])

  useEffect(() => { window.addEventListener('keydown', keyDown); return () => window.removeEventListener('keydown', keyDown) }, [keyDown])

  function align(modeName) { backend?.alignFields(JSON.stringify(selected), modeName) }
  function zoomBy(factor) { setZoom((value) => Math.max(40, Math.min(220, Math.round(value * factor / 5) * 5))) }
  function fitWidth() {
    const page = state.pages[state.page]
    const available = (scrollArea.current?.clientWidth || 960) - 76
    if (page) setZoom(Math.max(40, Math.min(220, Math.floor(available / page.width * 72 / 5) * 5)))
  }

  const page = state.pages[state.page]
  const pageWidth = page ? page.width * zoom / 72 : 612
  const pageHeight = page ? page.height * zoom / 72 : 792
  const activeReport = state.pending || state.report

  function runAutomatic() {
    backend?.autoAnalyze(JSON.stringify({ discover: autoIntent === 'find', scope: autoScope }))
    setDrawer('review')
  }

  function renderCanvasField(field) {
    const rect = dragPreview?.find((item) => item.key === field.key)?.rect || field.rect
    const [x0, y0, x1, y1] = rect
    const pw = page?.width || 612; const ph = page?.height || 792
    const selectedField = selected.includes(field.key)
    const style = {
      left: (x0 / pw * 100) + '%', top: ((ph - y1) / ph * 100) + '%',
      width: ((x1 - x0) / pw * 100) + '%', height: ((y1 - y0) / ph * 100) + '%',
      '--field-bg': (field.kind === 'rewrite' ? field.fill : field.background) || 'transparent', '--field-text': field.text_color || '#17212f',
      '--field-highlight': field.highlight || '#b99af1', '--field-font': (field.font_size * zoom / 72) + 'px',
    }
    const common = { className: 'pdfField ' + field.kind + (selectedField ? ' selected' : '') + (field.locked ? ' locked' : ''), style, onPointerDown: (event) => startGesture(event, field), onClick: (event) => { event.stopPropagation(); if (mode === 'layout') selectField(field, event.shiftKey || event.ctrlKey) } }
    if (field.kind === 'rewrite') return <div key={field.key} {...common} className={common.className + ' rewriteField'} title="Visible replacement; original text may remain searchable"><span>{(drafts[field.key] ?? field.text) || 'Replacement text'}</span>{selectedField && field.key === selected[0] && ['nw','ne','sw','se'].map((direction) => <span key={direction} role="presentation" className={'resizeHandle ' + direction} onPointerDown={(event) => startGesture(event, field, direction)} />)}</div>
    if (mode === 'fill') {
      if (field.kind === 'checkbox' || field.kind === 'radio') return <button key={field.key} {...common} className={common.className + ' fillChoice'} aria-label={field.tooltip || field.name} aria-pressed={field.checked} onClick={() => {
        if (field.kind === 'radio') setField(field, { checked: true })
        else setField(field, { checked: !field.checked })
      }}><span className={field.checked ? 'choiceChecked' : ''}>{field.checked && (field.kind === 'radio' ? <i className="radioDot" aria-hidden="true" /> : <X size={15} strokeWidth={3} aria-hidden="true" />)}</span></button>
      const value = drafts[field.key] ?? field.value ?? ''
      const inputProps = { value, maxLength: field.max_length || undefined, placeholder: field.tooltip || field.name, style: { fontSize: style['--field-font'], color: style['--field-text'], textAlign: ['left','center','right'][field.alignment] || 'left' }, onChange: (event) => setDrafts((old) => ({ ...old, [field.key]: event.target.value })), onBlur: () => { setField(field, { value }); setDrafts((old) => { const next = { ...old }; delete next[field.key]; return next }) }, onPointerDown: (event) => event.stopPropagation() }
      return <div key={field.key} {...common} className={common.className + ' fillText'}>{field.kind === 'choice' ? <select {...inputProps}>{(field.choices || []).map((option) => <option key={option}>{option}</option>)}</select> : field.multiline ? <textarea {...inputProps} /> : <input {...inputProps} type="text" />}</div>
    }
    return <div key={field.key} {...common}>
      {field.locked && <span className="lockBadge"><LockKeyhole size={11} /></span>}
      {selectedField && field.key === selected[0] && ['nw','ne','sw','se'].map((direction) => <span key={direction} role="presentation" className={'resizeHandle ' + direction} onPointerDown={(event) => startGesture(event, field, direction)} />)}
    </div>
  }

  function inspectorValue(field, key, value, opts = {}) {
    return <label className={'formField ' + (opts.wide ? 'wide' : '')} key={key}><span>{opts.label || key.replaceAll('_', ' ')}</span>{opts.textarea ? <textarea value={value ?? ''} rows={opts.rows || 3} onChange={(e) => opts.onChange ? opts.onChange(e.target.value) : setField(field, { [key]: e.target.value })} onBlur={opts.onBlur} /> : opts.type === 'color' ? <div className="colorControl"><input type="color" value={value || '#ffffff'} onChange={(e) => setField(field, { [key]: e.target.value })} /><code>{value || 'Transparent'}</code>{key === 'background' && <button className="quietIcon" title="Clear fill" onClick={() => setField(field, { background: null })}><Trash2 size={14} /></button>}</div> : opts.select ? <select value={value ?? opts.select[0]} onChange={(e) => setField(field, { [key]: opts.parse ? opts.parse(e.target.value) : e.target.value })}>{opts.select.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select> : <input type={opts.type || 'text'} value={value ?? ''} min={opts.min} max={opts.max} step={opts.step} onChange={(e) => setField(field, { [key]: opts.parse ? opts.parse(e.target.value) : opts.type === 'number' ? Number(e.target.value) : e.target.value })} />}</label>
  }

  function renderInspector() {
    if (drawer === 'review' && activeReport) return <ReviewPanel report={activeReport} pending={Boolean(state.pending)} backend={backend} onClose={() => setDrawer('')} onPage={changePage} onApply={() => backend?.applyAutomatic()} onDiscard={() => backend?.discardAutomatic()} />
    if (!current) return <div className="inspectorEmpty"><div className="emptyIcon"><MousePointer2 size={20} /></div><strong>{selected.length > 1 ? selected.length + ' fields selected' : 'Select a field'}</strong><p>{selected.length > 1 ? 'Drag to move together, or use the alignment controls.' : 'Choose a field on the page or in the list to edit its content, position and appearance.'}</p>{selected.length > 1 && <div className="alignTools"><button title="Align left" onClick={() => align('left')}><AlignLeft size={15} /></button><button title="Align horizontal centers" onClick={() => align('center')}><AlignCenter size={15} /></button><button title="Align right" onClick={() => align('right')}><AlignRight size={15} /></button><button title="Distribute horizontally" onClick={() => align('distribute')}><AlignHorizontalDistributeCenter size={15} /></button></div>}</div>
    return <>
      <div className="inspectorHeading"><div className="typeIcon">{iconFor(current.kind)}</div><div><span className="eyebrow">{current.kind==='rewrite'?'PAGE CONTENT':'FIELD SETTINGS'}</span><h2>{typeLabel[current.kind]}</h2></div>{current.kind!=='rewrite'&&<button className="quietIcon" title={current.locked ? 'Unlock field' : 'Lock field'} onClick={() => setField(current, { locked: !current.locked })}>{current.locked ? <LockKeyhole size={16} /> : <UnlockKeyhole size={16} />}</button>}{current.kind!=='rewrite'&&<button className="quietIcon" title="Duplicate field" onClick={() => backend?.duplicateField(current.key)}><Copy size={16} /></button>}</div>
      <div className="inspectorTabs" role="tablist">{[['content','Content'],['position','Position'],['appearance','Appearance'],['behavior','Logic']].map(([id,label]) => <button key={id} role="tab" aria-selected={activePanel === id} className={activePanel === id ? 'active' : ''} onClick={() => setActivePanel(id)}>{label}</button>)}</div>
      <div className="inspectorScroll">
        {activePanel === 'content' && <div className="inspectorSection">
          {current.kind==='rewrite' ? <>
            {inspectorValue(current,'text',drafts[current.key] ?? current.text,{label:'Replacement text',wide:true,textarea:true,rows:3,onChange:(value)=>setDrafts((old)=>({...old,[current.key]:value})),onBlur:()=>{if(drafts[current.key]!==undefined){setField(current,{text:drafts[current.key]});setDrafts((old)=>{const next={...old};delete next[current.key];return next})}}})}
            <Callout icon={CircleHelp} title="Visible correction only">This covers the printed area in the exported PDF. The original text may remain searchable; this is not secure redaction.</Callout>
          </> : <>
            {inspectorValue(current, current.kind === 'radio' ? 'group' : 'name', current.kind === 'radio' ? current.group : current.name, { label: current.kind === 'radio' ? 'Radio group' : 'Field name', wide: true })}
            {inspectorValue(current, 'tooltip', current.tooltip, { label: 'Form label / tooltip', wide: true })}
          </>}
          {current.kind === 'text' && <>
            {inspectorValue(current, 'value', drafts[current.key] ?? current.value, { label: 'Sample value', wide: true, textarea: current.multiline, onChange: (value) => setDrafts((old) => ({ ...old, [current.key]: value })), onBlur: () => { if (drafts[current.key] !== undefined) { setField(current, { value: drafts[current.key] }); setDrafts((old) => { const n = { ...old }; delete n[current.key]; return n }) } } })}
            <p className="fieldHint">This value appears in the exported form. Leave it empty for a blank field.</p>
          </>}
          {current.kind === 'choice' && <>
            {inspectorValue(current, 'choices', (current.choices || []).join('\n'), { label: 'Dropdown options', wide: true, textarea: true, rows: 5, onChange: (value) => setDrafts((old) => ({ ...old, [current.key + ':choices']: value })), onBlur: () => { if (drafts[current.key + ':choices'] !== undefined) { setField(current, { choices: drafts[current.key + ':choices'].split('\n').map((x) => x.trim()).filter(Boolean) }); setDrafts((old) => { const n={...old};delete n[current.key + ':choices'];return n }) } } })}
            <p className="fieldHint">Enter one choice per line.</p>
          </>}
          {current.kind === 'radio' && <>{inspectorValue(current,'option',current.option,{label:'Choice value',wide:true})}<p className="fieldHint">Options with this same group name are mutually exclusive.</p></>}
          {current.kind === 'checkbox' && <>{inspectorValue(current,'option',current.option,{label:'Export value',wide:true})}<Toggle label="Selected by default" checked={current.checked} onChange={(checked) => setField(current,{checked})} /></>}
        </div>}
        {activePanel === 'position' && <div className="inspectorSection">
          <div className="dimensionGrid">{[
            ['X',current.rect[0]],['Y from top',(state.pages[current.page]?.height || 792)-current.rect[3]],['Width',current.rect[2]-current.rect[0]],['Height',current.rect[3]-current.rect[1]],
          ].map(([label,value],index) => <label key={label} className="formField"><span>{label}</span><div className="numberWithUnit"><input type="number" step="0.1" value={Number(value.toFixed(2))} onChange={(e) => { const next=current.rect.slice();const v=Number(e.target.value);if(index===0){const w=next[2]-next[0];next[0]=v;next[2]=v+w}if(index===1){const h=next[3]-next[1];const top=(state.pages[current.page]?.height||792)-v;next[1]=top-h;next[3]=top}if(index===2)next[2]=next[0]+v;if(index===3)next[1]=next[3]-v;setField(current,{rect:next}) }} /><i>pt</i></div></label>)}</div>
          <label className="formField"><span>Page</span><select value={current.page} disabled><option>{current.page + 1}</option></select></label>
          <Callout icon={Focus} title="Canvas controls">Drag a selected field to move it. Pull a corner handle to resize. Arrow keys nudge by 1 pt; Shift + arrows nudge by 10 pt.</Callout>
        </div>}
        {activePanel === 'appearance' && <div className="inspectorSection">
          {(current.kind === 'text' || current.kind === 'choice' || current.kind==='rewrite') && <div className="dimensionGrid">
            {inspectorValue(current,'font_size',current.font_size,{label:'Text size',type:'number',min:1,max:100,step:.5})}
            {inspectorValue(current,'font',current.font,{label:'Font',select:['Helvetica','Times-Roman','Courier']})}
            {current.kind==='rewrite'&&<>{inspectorValue(current,'text_color',current.text_color,{label:'Replacement color',type:'color'})}{inspectorValue(current,'fill',current.fill,{label:'Cover color',type:'color'})}</>}
            {current.kind!=='rewrite'&&<>
            {inspectorValue(current,'alignment',current.alignment,{label:'Alignment',select:['Left','Center','Right'],parse:(v)=>['Left','Center','Right'].indexOf(v)})}
            {inspectorValue(current,'max_length',current.max_length,{label:'Character limit',type:'number',min:0,max:1000})}
            </>}
          </div>}
          {current.kind!=='rewrite'&&<Toggle label="Multiple lines" checked={current.multiline} onChange={(value) => setField(current,{multiline:value})} disabled={current.kind !== 'text'} />}
          {current.kind!=='rewrite'&&<div className="colorStack"><strong>Colors</strong>
            {inspectorValue(current,'text_color',current.text_color,{label:'Text',type:'color'})}
            {inspectorValue(current,'highlight',current.highlight,{label:'Editor highlight',type:'color'})}
            {inspectorValue(current,'background',current.background || '#ffffff',{label:'PDF fill',type:'color'})}
            {inspectorValue(current,'border_color',current.border_color,{label:'PDF border',type:'color'})}
          </div>}
          {current.kind!=='rewrite'&&inspectorValue(current,'border_width',current.border_width,{label:'Border width',type:'number',min:0,max:10,step:.1})}
          {current.kind!=='rewrite'&&<p className="fieldHint">Editor highlight shows field bounds while editing. PDF fill and border are saved into the exported form.</p>}
        </div>}
        {activePanel === 'behavior' && <div className="inspectorSection">
          {current.kind!=='rewrite'&&<Toggle label="Lock position" checked={current.locked} onChange={(value) => setField(current,{locked:value})} />}
          {current.kind === 'text' && <Toggle label="Multiple lines" checked={current.multiline} onChange={(value) => setField(current,{multiline:value})} />}
          {current.kind === 'checkbox' && <Toggle label="Selected by default" checked={current.checked} onChange={(value) => setField(current,{checked:value})} />}
          {(current.kind==='text'||current.kind==='choice')&&<>
            <div className="formField"><span>Automatically copy this value to</span><div className="linkTargets">{allItems.filter((item)=>['text','choice'].includes(item.kind)&&item.key!==current.key).length ? allItems.filter((item)=>['text','choice'].includes(item.kind)&&item.key!==current.key).map((item)=><label key={item.key} className="linkTarget"><input type="checkbox" checked={(current.linked_fields||[]).includes(item.key)} onChange={(event)=>{const links=new Set(current.linked_fields||[]);if(event.target.checked)links.add(item.key);else links.delete(item.key);setField(current,{linked_fields:[...links]})}}/><span><b>{item.name}</b><small>Page {item.page+1} · {item.kind==='choice'?'Dropdown':'Text'}</small></span></label>) : <p className="fieldHint">Add another text field or dropdown to create a link.</p>}</div></div>
            <p className="fieldHint">Values copy as you fill in the form. Save the project to keep these links; other PDF apps do not run Studio links.</p>
          </>}
          <Callout icon={ShieldCheck} title="PDF-safe editing">Field values and appearances are checked after export. The original page artwork remains unchanged.</Callout>
        </div>}
      </div>
      <div className="inspectorFooter"><button className="dangerButton" onClick={() => { if (window.confirm('Delete this field?')) { backend?.deleteFields(JSON.stringify([current.key]));setSelected([]) } }}><Trash2 size={14} /> Delete field</button></div>
    </>
  }

  return <main className="studio" onDragEnter={(e) => { if (e.dataTransfer?.types?.includes('Files')) setDragOver(true) }} onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false) }}>
    <header className="topbar">
      <div className="brand"><img src="./logo-wordmark.png" alt="Auto PDF Form" /><span className="brandDivider" /><span className="productMark">FORM STUDIO <i>1.1</i></span></div>
      <div className="documentName">{state.filename ? <><FileText size={15} /><span>{state.filename}</span>{state.dirty && <i className="dirtyDot" title="Unsaved changes" />}</> : <span className="muted">No PDF open</span>}</div>
      <div className="topActions">
        <button className="toolbarButton" title="Open PDF · Ctrl+O" onClick={() => backend?.openDialog()}><FolderIcon /> <span>Open PDF</span></button>
        <button className="toolbarButton" title="Save project · Ctrl+S" disabled={!state.source || state.busy} onClick={() => backend?.saveProject()}><ArrowDownToLine size={15} /><span>Save project</span></button>
        <button className="primaryButton" title="Export PDF · Ctrl+Shift+S" disabled={!state.source || state.busy} onClick={() => backend?.exportPDF()}><Upload size={15} />Export PDF</button>
      </div>
    </header>

    <nav className="commandBar" aria-label="Document editing actions">
      <div className="modeSwitch" role="tablist" aria-label="Editing mode"><button role="tab" aria-selected={mode==='layout'} className={mode==='layout'?'active':''} onClick={() => {setMode('layout');if(state.preview)backend?.togglePreview()}}><MousePointer2 size={14} /> Edit layout</button><button role="tab" aria-selected={mode==='fill'} className={mode==='fill'?'active':''} onClick={() => {setMode('fill');if(!state.preview)backend?.togglePreview()}}><FormInput size={14} /> Fill &amp; preview</button></div>
      <span className="toolbarSeparator" />
      <button className="autoAction" disabled={!state.source || state.busy || state.preview} onClick={() => setDrawer(drawer==='automatic'?'':'automatic')}><Sparkles size={15} /> Automatic <ChevronDown size={13} /></button>
      <button className="toolbarButton" disabled={!state.source || state.busy} onClick={() => backend?.templateDialog()}><Layers2 size={15} /> Template</button>
      <button className={'toolbarButton '+(activeReport?'hasReport':'')} disabled={!activeReport} onClick={() => setDrawer(drawer==='review'?'':'review')}><ShieldCheck size={15} /> Review {activeReport?.changes?.length ? <span className="countBadge">{activeReport.changes.length}</span> : null}</button>
      <div className="commandSpacer" />
      {selected.length > 1 && <div className="miniAlign"><span>{selected.length} selected</span><button title="Align left" onClick={() => align('left')}><AlignLeft size={14} /></button><button title="Align horizontal centers" onClick={() => align('center')}><AlignCenter size={14} /></button><button title="Distribute horizontally" onClick={() => align('distribute')}><AlignHorizontalDistributeCenter size={14} /></button></div>}
      <button className="quietIcon" title="Undo · Ctrl+Z" disabled={!state.canUndo || state.busy || state.preview} onClick={() => backend?.undo()}><RotateCcw size={15} /></button>
      <button className="quietIcon" title="Redo · Ctrl+Y" disabled={!state.canRedo || state.busy || state.preview} onClick={() => backend?.redo()}><RotateCw size={15} /></button>
    </nav>

    {drawer === 'automatic' && <section className="automaticPopover" aria-label="Automatic field detection"><div className="popoverHead"><div className="sparkIcon"><Sparkles size={17} /></div><div><strong>Automatic field setup</strong><p>Find likely answer areas, then review changes before applying.</p></div><button className="quietIcon" onClick={() => setDrawer('')} aria-label="Close"><ChevronDown size={16} /></button></div><div className="autoOptions"><label className="formField"><span>What should it do?</span><select value={autoIntent} onChange={(e)=>setAutoIntent(e.target.value)}><option value="find">Find missing fields and repair alignment</option><option value="repair">Repair existing field alignment only</option></select></label><label className="formField"><span>Scan pages</span><select value={autoScope} onChange={(e)=>setAutoScope(e.target.value)}><option value="all">All pages</option><option value="page">Current page only</option></select></label></div><div className="autoFoot"><span>Detected fields are staged for review.</span><button className="primaryButton" onClick={runAutomatic} disabled={!state.source || state.busy || state.preview}><Sparkles size={15} />{state.busy?'Analyzing…':'Analyze form'}</button></div></section>}

    {!state.source ? <section className="welcome"><div className="welcomeBadge"><FilePlus2 size={24} /></div><span className="eyebrow">A CLEARER WAY TO MAKE FILLABLE PDFS</span><h1>Your PDF stays yours.</h1><p>Set up fields on the original page, refine them visually, and export a fillable copy with its artwork intact.</p><div className="welcomeActions"><button className="primaryButton large" onClick={() => backend?.openDialog()}><Upload size={16} /> Open a PDF</button><span>or drop a PDF here</span></div><div className="welcomeSteps"><div><b>01</b><span>Analyze writing lines</span></div><div><b>02</b><span>Review every field</span></div><div><b>03</b><span>Export and validate</span></div></div><img className="welcomeLogo" src="./logo-icon.png" alt="" /></section> : <section className={'workspace '+(leftCollapsed?'leftCollapsed':'')}>
      {!leftCollapsed && <aside className="leftRail">
        <div className="railTabs"><button className={activeTab==='pages'?'active':''} onClick={()=>setActiveTab('pages')}><Grid2X2 size={14}/> Pages <span>{state.pages.length}</span></button><button className={activeTab==='fields'?'active':''} onClick={()=>setActiveTab('fields')}><Layers2 size={14}/> Fields <span>{allItems.length}</span></button></div>
        {activeTab === 'pages' ? <div className="pageList">{state.pages.map((item) => <button className={'pageCard '+(state.page===item.index?'active':'')} key={item.index} onClick={()=>changePage(item.index)}><div className="thumbWrap">{thumbnails[item.index] ? <img src={thumbnails[item.index]} alt={'Page '+(item.index+1)+' preview'} /> : <span className="thumbLoading" />}</div><div className="pageMeta"><span>PAGE {String(item.index+1).padStart(2,'0')}</span><b>{item.fields} {item.fields===1?'field':'fields'}</b></div>{state.page===item.index&&<span className="activePageDot"/>}</button>)}</div> : <div className="fieldListPanel">
          <div className="searchField"><Search size={15}/><input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search field names" /><kbd>⌘ K</kbd></div>
          <div className="filterRow"><label><Filter size={13}/><select value={kindFilter} onChange={(e)=>setKindFilter(e.target.value)}><option value="all">All field types</option><option value="text">Text</option><option value="choice">Dropdown</option><option value="checkbox">Checkbox</option><option value="radio">Radio</option><option value="rewrite">Text corrections</option></select></label><button className={'scopeSwitch '+(allPages?'active':'')} onClick={()=>setAllPages(!allPages)}>{allPages?'All pages':'This page'}</button></div>
          <div className="fieldRows">{shownFields.length ? shownFields.map((field)=> <button key={field.key} className={'fieldRow '+(selected.includes(field.key)?'active':'')} onClick={(e)=>selectField(field,e.shiftKey||e.ctrlKey)}><span className={'fieldRowIcon '+field.kind}>{iconFor(field.kind)}</span><span className="fieldRowName">{field.name}<small>{field.kind==='radio'?field.option:field.kind==='rewrite'?'Text correction':shortType[field.kind]} · Page {field.page+1}</small></span>{field.locked&&<LockKeyhole size={12} className="mutedIcon"/>}</button>) : <div className="noFields">No fields match these filters.</div>}</div>
        </div>}
        <div className="railFooter"><span><span className="liveDot"/>{state.fields.length} widgets · {(state.rewrites||[]).length} text corrections</span><button className="quietIcon" onClick={()=>setLeftCollapsed(true)} title="Collapse sidebar"><PanelLeftClose size={15}/></button></div>
      </aside>}

      <section className="canvasArea">
        <div className="canvasToolbar"><div className="canvasTitle"><button className="quietIcon revealRail" onClick={()=>setLeftCollapsed(false)} title="Show pages and fields"><PanelLeftOpen size={15}/></button><span>{state.preview?'Filled PDF preview':'Page '+(state.page+1)+' of '+state.pages.length}</span>{state.busy&&<i className="busySpinner"/>}</div><div className="canvasTools">{mode==='layout'&&!state.preview&&<div className="addFieldMenu"><button className="toolbarButton" onClick={(e)=>{const menu=e.currentTarget.nextElementSibling;menu.hidden=!menu.hidden}}><Plus size={15}/> Add field <ChevronDown size={12}/></button><div className="addMenu" hidden><button onClick={()=>backend?.addField('text')}><TextCursorInput size={15}/> Text field</button><button onClick={()=>backend?.addField('choice')}><ChevronDown size={15}/> Dropdown</button><button onClick={()=>backend?.addField('checkbox')}><Square size={15}/> Checkbox</button><button onClick={()=>backend?.addField('radio')}><span className="radioGlyph"/> Radio option</button><button onClick={()=>{backend?.addRewrite();setActiveTab('fields')}}><FileText size={15}/> Cover &amp; replace text…</button></div></div>}
          <button className="quietIcon" title="Zoom out" onClick={()=>zoomBy(.9)} disabled={!state.source}><ZoomOut size={15}/></button><select aria-label="Zoom" className="zoomSelect" value={zoom} onChange={(e)=>setZoom(Number(e.target.value))}>{[50,60,75,90,100,110,125,150,175,200].map((value)=><option key={value} value={value}>{value}%</option>)}</select><button className="quietIcon" title="Zoom in" onClick={()=>zoomBy(1.1)} disabled={!state.source}><ZoomIn size={15}/></button><button className="toolbarButton fitButton" onClick={fitWidth}><Maximize2 size={14}/> Fit</button>
        </div></div>
        <div className="canvasScroll" ref={scrollArea}>
          {state.busy && state.fields.length===0 && <div className="canvasLoading"><span className="largeSpinner"/><strong>Opening your PDF…</strong><p>Reading page sizes and existing form fields.</p></div>}
          {page && <div className="pageFrame" style={{width:pageWidth+'px',minHeight:pageHeight+'px',aspectRatio:page.width+'/'+page.height}} onClick={()=>setSelected([])}>
            {pageImage?.source===state.source&&pageImage?.page===state.page ? <img className="pageImage" src={pageImage.image} alt={'PDF page '+(state.page+1)} draggable="false" /> : <div className="pageImagePlaceholder"><span className="largeSpinner"/><span>Rendering page</span></div>}
            {!state.preview&&allItems.filter((field)=>field.page===state.page).map(renderCanvasField)}
          </div>}
        </div>
        <footer className="canvasStatus"><span>{state.source ? state.preview?'Sample values shown for review':'Drag fields to move · Pull a corner to resize · Shift-click to select more' : 'Ready to open a PDF'}</span><span>{page ? Math.round(page.width)+' × '+Math.round(page.height)+' pt' : ''}</span></footer>
      </section>

      <aside className="inspector">
        <div className="inspectorTop"><span className="eyebrow">{drawer==='review'&&activeReport?'AUTOMATIC REVIEW':'PROPERTIES'}</span>{drawer==='review'&&activeReport?<button className="quietIcon" title="Close review" onClick={()=>setDrawer('')}><ChevronRight size={15}/></button>:<Settings2 size={15}/>}</div>
        {drawer==='automatic'&&<div className="inlineAuto"><span>Automatic setup</span><button onClick={runAutomatic}><Sparkles size={14}/> Analyze</button></div>}
        {renderInspector()}
      </aside>
    </section>}

    <footer className="bottomBar"><div><span className="liveDot"/>{state.busy?'Working…':state.filename?state.dirty?'Unsaved changes':'All changes saved':'Local PDF editor'}</div><div><span>Ctrl+O Open</span><span>Ctrl+S Save</span><span>Ctrl+Z Undo</span><span>PDF content stays on this device</span></div></footer>
    {toast&&<div className="toast"><Check size={15}/>{toast}</div>}
    {dragOver&&<div className="dropOverlay" onDragLeave={()=>setDragOver(false)}><div><Upload size={26}/><strong>Drop your PDF to open it</strong><span>Existing PDF form projects are supported too.</span></div></div>}
  </main>
}

function Toggle({ label, checked, onChange, disabled = false }) {
  return <label className={'toggleRow '+(disabled?'disabled':'')}><span>{label}</span><button type="button" role="switch" aria-checked={checked} disabled={disabled} className={'toggle '+(checked?'on':'')} onClick={()=>onChange(!checked)}><i/></button></label>
}

function ReviewPanel({ report, pending, backend, onClose, onPage, onApply, onDiscard }) {
  const changes=report?.changes || []
  const review=report?.review || []
  return <div className="reviewPanel">
    <div className="reviewSummary"><div className="reviewSummaryIcon"><Sparkles size={18}/></div><strong>{pending?'Suggestions are ready':'Analysis summary'}</strong><p>{changes.length} proposed changes across {report?.pages || 0} page{report?.pages===1?'':'s'}. {pending?'Nothing is changed until you apply these suggestions.':'Review warnings before exporting.'}</p><div className="reviewStats"><div><b>{changes.length}</b><span>proposals</span></div><div><b>{report?.field_widgets ?? 0}</b><span>field widgets</span></div><div><b>{review.length}</b><span>review notes</span></div></div></div>
    <div className="reviewListHead"><strong>Proposed changes</strong><span>{changes.filter((item)=>item.confidence==='high').length} high confidence</span></div>
    <div className="reviewChanges">{changes.length ? changes.map((change,index)=><button className="reviewChange" key={index} onClick={()=>onPage(Math.max(0,(change.page||1)-1))}><span className={'confidenceDot '+(change.confidence==='high'?'high':'review')}/><span className="reviewChangeBody"><b>{change.field || 'Detected field'}</b><small>Page {change.page || '—'} · {change.action}</small><em>{change.reason || 'Review this suggestion on the page before accepting it.'}</em></span><ChevronRight size={14}/></button>) : <div className="noFields">No new automatic changes were suggested.</div>}</div>
    {review.length>0&&<div className="reviewNotes"><strong>Review notes</strong>{review.map((item,index)=><p key={index}><CircleHelp size={13}/>{item}</p>)}</div>}
    {pending&&<div className="reviewActions"><button className="toolbarButton" onClick={onDiscard}>Discard suggestions</button><button className="primaryButton" onClick={onApply}><Check size={15}/> Apply all suggestions</button></div>}
    {!pending&&<button className="toolbarButton reanalyze" onClick={()=>backend?.autoAnalyze(JSON.stringify({discover:true,scope:'all'}))}><RotateCw size={14}/> Analyze again</button>}
    <button className="reviewClose" onClick={onClose}>Back to field settings</button>
  </div>
}

function FolderIcon() { return <FileText size={15} /> }

export default App
