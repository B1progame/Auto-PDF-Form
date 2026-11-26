import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  AlignCenter, AlignHorizontalDistributeCenter, AlignLeft, AlignRight, ArrowDownToLine,
  Check, ChevronDown, ChevronRight,
  CircleHelp, Copy, Download, FilePlus2, FileText, Filter, Focus, FormInput, Grid2X2,
  Layers2, LockKeyhole, Maximize2, MousePointer2, PanelLeftClose, PanelLeftOpen,
  Plus, RotateCcw, RotateCw, Search, ShieldCheck, Sparkles, Square,
  TextCursorInput, Trash2, UnlockKeyhole, Upload, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import './App.css'

const typeLabel = { text: 'Text field', choice: 'Dropdown', checkbox: 'Checkbox', radio: 'Radio option', rewrite: 'Printed text correction' }
const shortType = { text: 'Text', choice: 'Dropdown', checkbox: 'Checkbox', radio: 'Radio' }

function storedWidth(key, fallback, min, max) {
  try { return Math.max(min, Math.min(max, Number(window.localStorage?.getItem(key)) || fallback)) }
  catch { return fallback }
}

function storedBoolean(key, fallback = false) {
  try { const value=window.localStorage?.getItem(key); return value==null ? fallback : value === 'true' }
  catch { return fallback }
}

function iconFor(kind) {
  if (kind === 'checkbox') return <Square size={15} />
  if (kind === 'radio') return <span className="radioGlyph" />
  if (kind === 'choice') return <ChevronDown size={15} />
  return <TextCursorInput size={15} />
}

function markerFor(field) {
  const style = field.marker_style && field.marker_style !== 'default'
    ? field.marker_style
    : field.kind === 'radio' ? 'dot' : 'x'
  if (style === 'none') return null
  if (style === 'fill') return <i className="markFill" aria-hidden="true" />
  if (style === 'check') return <Check className="markCheck" aria-hidden="true" />
  if (style === 'dot') return <i className="markDot" aria-hidden="true" />
  return <X className="markX" aria-hidden="true" />
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
  const [leftWidth, setLeftWidth] = useState(() => storedWidth('studio.leftWidth',254,190,420))
  const [rightWidth, setRightWidth] = useState(() => storedWidth('studio.rightWidth',306,250,520))
  const [toast, setToast] = useState('')
  const [drawer, setDrawer] = useState('')
  const [autoScope, setAutoScope] = useState('all')
  const [autoIntent, setAutoIntent] = useState('find')
  const [drafts, setDrafts] = useState({})
  const [dragPreview, setDragPreview] = useState(null)
  const [leftCollapsed, setLeftCollapsed] = useState(() => storedBoolean('studio.leftCollapsed'))
  const [rightCollapsed, setRightCollapsed] = useState(() => storedBoolean('studio.rightCollapsed'))
  const [dragOver, setDragOver] = useState(false)
  const [updateDialog, setUpdateDialog] = useState(null)
  const scrollArea = useRef(null)
  const pageFrame = useRef(null)
  const pendingZoomAnchor = useRef(null)
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
          if (event.type === 'update') setUpdateDialog((previous) => previous ? ({ ...previous, ...event }) : previous)
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

  useEffect(() => { try { window.localStorage?.setItem?.('studio.leftWidth', String(leftWidth)) } catch { /* persistent browser storage is optional */ } }, [leftWidth])
  useEffect(() => { try { window.localStorage?.setItem?.('studio.rightWidth', String(rightWidth)) } catch { /* persistent browser storage is optional */ } }, [rightWidth])
  useEffect(() => { try { window.localStorage?.setItem?.('studio.leftCollapsed', String(leftCollapsed)); window.localStorage?.setItem?.('studio.rightCollapsed', String(rightCollapsed)) } catch { /* persistent browser storage is optional */ } }, [leftCollapsed,rightCollapsed])

  useLayoutEffect(() => {
    const anchor = pendingZoomAnchor.current
    const area = scrollArea.current
    const frame = pageFrame.current
    if (!anchor || !area || !frame) return
    const areaRect = area.getBoundingClientRect()
    const frameRect = frame.getBoundingClientRect()
    area.scrollLeft += frameRect.left - areaRect.left + anchor.xRatio * frameRect.width - anchor.clientX
    area.scrollTop += frameRect.top - areaRect.top + anchor.yRatio * frameRect.height - anchor.clientY
    pendingZoomAnchor.current = null
  }, [zoom])

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

  useEffect(() => {
    const area = scrollArea.current
    if (!area) return undefined
    const onWheel = (event) => {
      if (!event.ctrlKey || !state.source || state.preview || !pageFrame.current) return
      if (event.deltaY === 0) return
      event.preventDefault()
      const frame = pageFrame.current.getBoundingClientRect()
      const areaRect = area.getBoundingClientRect()
      const nextZoom = Math.max(40, Math.min(220, zoom + (event.deltaY < 0 ? 10 : -10)))
      pendingZoomAnchor.current = {
        clientX: event.clientX - areaRect.left, clientY: event.clientY - areaRect.top,
        xRatio: Math.max(0, Math.min(1, (event.clientX - frame.left) / frame.width)),
        yRatio: Math.max(0, Math.min(1, (event.clientY - frame.top) / frame.height)),
      }
      setZoom(nextZoom)
    }
    area.addEventListener('wheel', onWheel, { passive: false })
    return () => area.removeEventListener('wheel', onWheel)
  }, [state.source, state.preview, zoom])

  function align(modeName) { backend?.alignFields(JSON.stringify(selected), modeName) }
  function setEditorMode(nextMode) {
    if (nextMode === 'preview') {
      setMode('preview')
      if (!state.preview) backend?.togglePreview()
      return
    }
    setMode(nextMode)
    if (state.preview) backend?.togglePreview()
  }
  function fitWidth() {
    const page = state.pages[state.page]
    const available = (scrollArea.current?.clientWidth || 960) - 76
    if (page) setZoom(Math.max(40, Math.min(220, Math.floor(available / page.width * 72 / 10) * 10)))
  }
  function fitPage() {
    const currentPage = state.pages[state.page]
    const area = scrollArea.current
    if (!currentPage || !area) return
    const availableWidth = area.clientWidth - 60
    const availableHeight = area.clientHeight - 60
    const scale = Math.min(availableWidth / currentPage.width, availableHeight / currentPage.height) * 72
    setZoom(Math.max(40, Math.min(220, Math.floor(scale / 10) * 10)))
    area.scrollLeft = 0
    area.scrollTop = 0
  }

  function readUpdateResponse(result) {
    if (typeof result !== 'string') return
    try {
      const parsed = JSON.parse(result)
      if (parsed && typeof parsed === 'object') setUpdateDialog((previous) => ({ ...(previous || {}), ...parsed }))
    } catch { /* queued/status strings are completed through the update signal */ }
  }
  function checkForUpdates() {
    if (typeof backend?.checkForUpdates !== 'function') return
    setUpdateDialog({ status: 'checking' })
    readUpdateResponse(backend.checkForUpdates())
  }
  function openUpdateDialog() {
    if (typeof backend?.checkForUpdates !== 'function') return
    setUpdateDialog({ status: 'checking' })
    readUpdateResponse(backend.checkForUpdates())
  }
  function runUpdateAction(action) {
    const method = { download: 'downloadUpdate', cancel: 'cancelUpdate', install: 'installUpdate' }[action]
    if (typeof backend?.[method] === 'function') readUpdateResponse(backend[method]())
  }

  const hasUpdater = ['checkForUpdates','downloadUpdate','cancelUpdate','installUpdate'].every((name)=>typeof backend?.[name]==='function')

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
    const answerMark = field.checked && ['checkbox','radio'].includes(field.kind) ? markerFor(field) : null
    const style = {
      left: (x0 / pw * 100) + '%', top: ((ph - y1) / ph * 100) + '%',
      width: ((x1 - x0) / pw * 100) + '%', height: ((y1 - y0) / ph * 100) + '%',
      '--field-bg': (field.kind === 'rewrite' ? field.fill : field.background) || 'transparent', '--field-text': field.text_color || '#17212f',
      '--field-highlight': field.highlight || '#b99af1', '--field-font': (field.font_size * zoom / 72) + 'px',
    }
    const common = { className: 'pdfField ' + field.kind + (selectedField ? ' selected' : '') + (field.locked ? ' locked' : ''), style, onPointerDown: (event) => startGesture(event, field), onClick: (event) => { event.stopPropagation(); if (mode === 'layout') selectField(field, event.shiftKey || event.ctrlKey) } }
    if (field.kind === 'rewrite') return <div key={field.key} {...common} className={common.className + ' rewriteField'} title="Visible replacement; original text may remain searchable"><span>{(drafts[field.key] ?? field.text) || 'Replacement text'}</span>{selectedField && field.key === selected[0] && ['nw','ne','sw','se'].map((direction) => <span key={direction} role="presentation" className={'resizeHandle ' + direction} onPointerDown={(event) => startGesture(event, field, direction)} />)}</div>
    if (mode === 'fill') {
      if (field.kind === 'checkbox' || field.kind === 'radio') return <button key={field.key} {...common} className={'pdfField '+field.kind+' fillChoice'} role={field.kind === 'radio' ? 'radio' : 'checkbox'} aria-label={field.tooltip || field.name} aria-checked={field.checked} onPointerDown={(event)=>event.stopPropagation()} onClick={() => {
        if (field.kind === 'radio') setField(field, { checked: true })
        else setField(field, { checked: !field.checked })
      }}><span className={'fillMark '+(field.checked?'checked':'')+' mark-'+(field.marker_style && field.marker_style!=='default'?field.marker_style:field.kind==='radio'?'dot':'x')}>{field.checked?markerFor(field):null}</span></button>
      const value = drafts[field.key] ?? field.value ?? ''
      const inputProps = { value, maxLength: field.max_length || undefined, placeholder: field.tooltip || field.name, style: { fontSize: style['--field-font'], color: style['--field-text'], textAlign: ['left','center','right'][field.alignment] || 'left' }, onChange: (event) => setDrafts((old) => ({ ...old, [field.key]: event.target.value })), onBlur: () => { setField(field, { value }); setDrafts((old) => { const next = { ...old }; delete next[field.key]; return next }) }, onPointerDown: (event) => event.stopPropagation() }
      return <div key={field.key} {...common} className={common.className + ' fillText'}>{field.kind === 'choice' ? <select {...inputProps}>{(field.choices || []).map((option) => <option key={option}>{option}</option>)}</select> : field.multiline ? <textarea {...inputProps} /> : <input {...inputProps} type="text" />}</div>
    }
    return <div key={field.key} {...common}>
      {answerMark&&<span className={'answerMark '+field.kind} aria-hidden="true">{answerMark}</span>}
      {field.locked && <span className="lockBadge"><LockKeyhole size={11} /></span>}
      {selectedField && field.key === selected[0] && ['nw','ne','sw','se'].map((direction) => <span key={direction} role="presentation" className={'resizeHandle ' + direction} onPointerDown={(event) => startGesture(event, field, direction)} />)}
    </div>
  }

  function inspectorValue(field, key, value, opts = {}) {
    return <label className={'formField ' + (opts.wide ? 'wide' : '')} key={key}><span>{opts.label || key.replaceAll('_', ' ')}</span>{opts.textarea ? <textarea value={value ?? ''} rows={opts.rows || 3} onChange={(e) => opts.onChange ? opts.onChange(e.target.value) : setField(field, { [key]: e.target.value })} onBlur={opts.onBlur} /> : opts.type === 'color' ? <div className="colorControl"><input type="color" value={value || '#ffffff'} onChange={(e) => setField(field, { [key]: e.target.value })} /><code>{value || 'Transparent'}</code>{key === 'background' && <button className="quietIcon" title="Clear fill" onClick={() => setField(field, { background: null })}><Trash2 size={14} /></button>}</div> : opts.select ? <select value={value ?? opts.select[0]} onChange={(e) => setField(field, { [key]: opts.parse ? opts.parse(e.target.value) : e.target.value })}>{opts.select.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select> : <input type={opts.type || 'text'} value={value ?? ''} min={opts.min} max={opts.max} step={opts.step} onChange={(e) => setField(field, { [key]: opts.parse ? opts.parse(e.target.value) : opts.type === 'number' ? Number(e.target.value) : e.target.value })} />}</label>
  }

  function renderInspector() {
    if (drawer === 'review' && activeReport) return <ReviewPanel report={activeReport} pending={Boolean(state.pending)} backend={backend} onClose={() => setDrawer('')} onPage={changePage} onApply={() => backend?.applyAutomatic()} onDiscard={() => backend?.discardAutomatic()} />
    if (!current) return <div className="inspectorEmpty"><div className="emptyIcon"><MousePointer2 size={20} /></div><strong>{selected.length > 1 ? selected.length + ' fields selected' : 'Select a field'}</strong><p>{selected.length > 1 ? 'Drag to move together, or use the alignment controls.' : 'Choose a field on the page or in the list to edit its content, position and appearance.'}</p>{selected.length > 1 ? <div className="alignTools"><button title="Align left" onClick={() => align('left')}><AlignLeft size={15} /></button><button title="Align horizontal centers" onClick={() => align('center')}><AlignCenter size={15} /></button><button title="Align right" onClick={() => align('right')}><AlignRight size={15} /></button><button title="Distribute horizontally" onClick={() => align('distribute')}><AlignHorizontalDistributeCenter size={15} /></button></div> : state.source&&mode==='layout'&&<div className="emptyActions"><button className="toolbarButton" onClick={()=>backend?.addField('text')}><TextCursorInput size={14}/> Add text</button><button className="toolbarButton" onClick={()=>backend?.addField('checkbox')}><Square size={14}/> Add checkbox</button><button className="toolbarButton" onClick={()=>backend?.addField('radio')}><span className="radioGlyph"/> Add radio</button><button className="toolbarButton" onClick={()=>{setDrawer('automatic')}}><Sparkles size={14}/> Find fields</button></div>}</div>
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
          {(current.kind==='checkbox'||current.kind==='radio')&&inspectorValue(current,'marker_style',current.marker_style||'default',{label:'Selected mark',select:current.kind==='checkbox'?['default','x','check','fill','none']:['default','dot','fill','none']})}
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
            <div className="formField"><span>Automatically send this value to</span><div className="linkTargets">{allItems.filter((item)=>['text','choice'].includes(item.kind)&&item.key!==current.key).length ? allItems.filter((item)=>['text','choice'].includes(item.kind)&&item.key!==current.key).map((item)=>{const linked=(current.linked_fields||[]).includes(item.key);const rule=(current.link_rules||{})[item.key]||{transform:'copy',condition:'always',date_part:'day',prefix:'',suffix:''};const updateRule=(patch)=>setField(current,{link_rules:{...(current.link_rules||{}),[item.key]:{...rule,...patch}}});return <div key={item.key} className="linkRuleCard"><label className="linkTarget"><input type="checkbox" checked={linked} onChange={(event)=>{const links=new Set(current.linked_fields||[]);if(event.target.checked)links.add(item.key);else links.delete(item.key);setField(current,{linked_fields:[...links]})}}/><span><b>{item.name}</b><small>Page {item.page+1} · {item.kind==='choice'?'Dropdown':'Text'}</small></span></label>{linked&&<div className="linkRuleControls"><label className="formField"><span>Transform</span><select aria-label={'Transform for '+item.name} value={rule.transform||'copy'} onChange={(event)=>updateRule({transform:event.target.value})}><option value="copy">Copy exactly</option><option value="uppercase">UPPERCASE</option><option value="lowercase">lowercase</option><option value="trim">Trim spaces</option><option value="prefix_suffix">Add prefix / suffix</option><option value="date_part">Copy date part</option></select></label><label className="formField"><span>When to update</span><select aria-label={'Condition for '+item.name} value={rule.condition||'always'} onChange={(event)=>updateRule({condition:event.target.value})}><option value="always">Always</option><option value="source_non_empty">Only if source has a value</option><option value="target_empty">Only if target is empty</option></select></label>{rule.transform==='date_part'&&<label className="formField"><span>Date component</span><select aria-label={'Date component for '+item.name} value={rule.date_part||'day'} onChange={(event)=>updateRule({date_part:event.target.value})}><option value="day">Day</option><option value="month">Month</option><option value="year">Year</option></select></label>}{rule.transform==='prefix_suffix'&&<><label className="formField"><span>Prefix</span><input aria-label={'Prefix for '+item.name} value={rule.prefix||''} maxLength={120} onChange={(event)=>updateRule({prefix:event.target.value})}/></label><label className="formField"><span>Suffix</span><input aria-label={'Suffix for '+item.name} value={rule.suffix||''} maxLength={120} onChange={(event)=>updateRule({suffix:event.target.value})}/></label></>}</div>}</div>}) : <p className="fieldHint">Add another text field or dropdown to create a link.</p>}</div></div>
            <p className="fieldHint">Linked values update inside Studio and are saved in the editable project. Dropdown targets must contain the transformed value. Other PDF readers do not run Studio link rules.</p>
          </>}
          <Callout icon={ShieldCheck} title="PDF-safe editing">Field values and appearances are checked after export. The original page artwork remains unchanged.</Callout>
        </div>}
      </div>
      <div className="inspectorFooter"><button className="dangerButton" onClick={() => { if (window.confirm('Delete this field?')) { backend?.deleteFields(JSON.stringify([current.key]));setSelected([]) } }}><Trash2 size={14} /> Delete field</button></div>
    </>
  }

  return <main className="studio" onDragEnter={(e) => { if (e.dataTransfer?.types?.includes('Files')) setDragOver(true) }} onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false) }}>
    <header className="topbar">
      <div className="brand"><img src="./logo-wordmark.png" alt="Auto PDF Form" /><span className="brandDivider" /><span className="productMark">FORM STUDIO{state.appVersion && <i>{state.appVersion.split('.').slice(0, 2).join('.')}</i>}</span></div>
      <div className="documentName">{state.filename ? <><FileText size={15} /><span>{state.filename}</span>{state.dirty && <i className="dirtyDot" title="Unsaved changes" />}</> : <span className="muted">No PDF open</span>}</div>
      <div className="topActions">
        <button className="toolbarButton" title="Open PDF · Ctrl+O" onClick={() => backend?.openDialog()}><FolderIcon /> <span>Open PDF</span></button>
        <button className="toolbarButton" title="Save project · Ctrl+S" disabled={!state.source || state.busy} onClick={() => backend?.saveProject()}><ArrowDownToLine size={15} /><span>Save project</span></button>
        {hasUpdater&&<button className="toolbarButton helpUpdateButton" title="Help and check for updates" onClick={openUpdateDialog}><CircleHelp size={15}/><span>Help &amp; updates</span></button>}
        <button className="primaryButton" title="Export PDF · Ctrl+Shift+S" disabled={!state.source || state.busy} onClick={() => backend?.exportPDF()}><Upload size={15} />Export PDF</button>
      </div>
    </header>

    <nav className="commandBar" aria-label="Document editing actions">
      <div className="modeSwitch" role="tablist" aria-label="Editing mode"><button role="tab" aria-selected={mode==='layout'} className={mode==='layout'?'active':''} onClick={() => setEditorMode('layout')}><MousePointer2 size={14} /> Design form</button><button role="tab" aria-selected={mode==='fill'} className={mode==='fill'?'active':''} onClick={() => setEditorMode('fill')}><FormInput size={14} /> Fill form</button><button role="tab" aria-selected={mode==='preview'} className={mode==='preview'?'active':''} onClick={() => setEditorMode('preview')}><FileText size={14} /> Preview PDF</button></div>
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

    {!state.source ? <section className="welcome"><div className="welcomeBadge"><FilePlus2 size={24} /></div><span className="eyebrow">A CLEARER WAY TO MAKE FILLABLE PDFS</span><h1>Your PDF stays yours.</h1><p>Set up fields on the original page, refine them visually, and export a fillable copy with its artwork intact.</p><div className="welcomeActions"><button className="primaryButton large" onClick={() => backend?.openDialog()}><Upload size={16} /> Open a PDF</button><span>or drop a PDF here</span></div><div className="welcomeSteps"><div><b>01</b><span>Analyze writing lines</span></div><div><b>02</b><span>Review every field</span></div><div><b>03</b><span>Export and validate</span></div></div><img className="welcomeLogo" src="./logo-icon.png" alt="" /></section> : <section className={'workspace '+(leftCollapsed?'leftCollapsed ':'')+(rightCollapsed?'rightCollapsed':'')} style={{'--left-width':`${leftWidth}px`,'--right-width':`${rightWidth}px`}}>
      {!leftCollapsed && <aside className="leftRail">
        <div className="railTabs"><button className={activeTab==='pages'?'active':''} onClick={()=>setActiveTab('pages')}><Grid2X2 size={14}/> Pages <span>{state.pages.length}</span></button><button className={activeTab==='fields'?'active':''} onClick={()=>setActiveTab('fields')}><Layers2 size={14}/> Fields <span>{allItems.length}</span></button></div>
        {activeTab === 'pages' ? <div className="pageList">{state.pages.map((item) => <button className={'pageCard '+(state.page===item.index?'active':'')} key={item.index} onClick={()=>changePage(item.index)}><div className="thumbWrap">{thumbnails[item.index] ? <img src={thumbnails[item.index]} alt={'Page '+(item.index+1)+' preview'} /> : <span className="thumbLoading" />}</div><div className="pageMeta"><span>PAGE {String(item.index+1).padStart(2,'0')}</span><b>{item.fields} {item.fields===1?'field':'fields'}</b></div>{state.page===item.index&&<span className="activePageDot"/>}</button>)}</div> : <div className="fieldListPanel">
          <div className="searchField"><Search size={15}/><input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search field names" /><kbd>⌘ K</kbd></div>
          <div className="filterRow"><label><Filter size={13}/><select value={kindFilter} onChange={(e)=>setKindFilter(e.target.value)}><option value="all">All field types</option><option value="text">Text</option><option value="choice">Dropdown</option><option value="checkbox">Checkbox</option><option value="radio">Radio</option><option value="rewrite">Text corrections</option></select></label><button className={'scopeSwitch '+(allPages?'active':'')} onClick={()=>setAllPages(!allPages)}>{allPages?'All pages':'This page'}</button></div>
          <div className="fieldRows">{shownFields.length ? shownFields.map((field)=> <button key={field.key} className={'fieldRow '+(selected.includes(field.key)?'active':'')} onClick={(e)=>selectField(field,e.shiftKey||e.ctrlKey)}><span className={'fieldRowIcon '+field.kind}>{iconFor(field.kind)}</span><span className="fieldRowName">{field.name}<small>{field.kind==='radio'?field.option:field.kind==='rewrite'?'Text correction':shortType[field.kind]} · Page {field.page+1}</small></span>{field.locked&&<LockKeyhole size={12} className="mutedIcon"/>}</button>) : <div className="noFields">No fields match these filters.</div>}</div>
        </div>}
        <div className="railFooter"><span><span className="liveDot"/>{state.fields.length} widgets · {(state.rewrites||[]).length} text corrections</span><button className="quietIcon" onClick={()=>setLeftCollapsed(true)} title="Collapse sidebar"><PanelLeftClose size={15}/></button></div>
      </aside>}
      {!leftCollapsed&&<PanelSplitter side="left" value={leftWidth} min={190} max={420} onChange={setLeftWidth} label="Resize pages and fields panel" />}

      <section className="canvasArea">
        <div className="canvasToolbar"><div className="canvasTitle"><button className="quietIcon revealRail" onClick={()=>setLeftCollapsed(false)} title="Show pages and fields"><PanelLeftOpen size={15}/></button><button className="quietIcon revealInspector" onClick={()=>setRightCollapsed(false)} title="Show Properties"><PanelLeftOpen size={15}/></button><span>{state.preview?'Export preview':mode==='fill'?'Fill form · Page '+(state.page+1)+' of '+state.pages.length:'Page '+(state.page+1)+' of '+state.pages.length}</span>{state.busy&&<i className="busySpinner"/>}</div><div className="canvasTools">{mode==='layout'&&!state.preview&&<div className="addFieldMenu"><button className="toolbarButton" onClick={(e)=>{const menu=e.currentTarget.nextElementSibling;menu.hidden=!menu.hidden}}><Plus size={15}/> Add field <ChevronDown size={12}/></button><div className="addMenu" hidden><button onClick={()=>backend?.addField('text')}><TextCursorInput size={15}/> Text field</button><button onClick={()=>backend?.addField('choice')}><ChevronDown size={15}/> Dropdown</button><button onClick={()=>backend?.addField('checkbox')}><Square size={15}/> Checkbox</button><button onClick={()=>backend?.addField('radio')}><span className="radioGlyph"/> Radio option</button><button onClick={()=>{backend?.addRewrite();setActiveTab('fields')}}><FileText size={15}/> Cover &amp; replace text…</button></div></div>}
          <button className="quietIcon" title="Zoom out by 10%" onClick={()=>setZoom((value)=>Math.max(40,value-10))} disabled={!state.source}><ZoomOut size={15}/></button><select aria-label="Zoom" className="zoomSelect" value={zoom} onChange={(e)=>setZoom(Number(e.target.value))}>{Array.from({length:19},(_,index)=>40+index*10).map((value)=><option key={value} value={value}>{value}%</option>)}</select><button className="quietIcon" title="Zoom in by 10%" onClick={()=>setZoom((value)=>Math.min(220,value+10))} disabled={!state.source}><ZoomIn size={15}/></button><button className="toolbarButton fitButton" onClick={fitWidth}><Maximize2 size={14}/> Fit width</button><button className="toolbarButton" onClick={fitPage}>Fit page</button>
        </div></div>
        <div className="canvasScroll" ref={scrollArea}>
          {state.busy && state.fields.length===0 && <div className="canvasLoading"><span className="largeSpinner"/><strong>Opening your PDF…</strong><p>Reading page sizes and existing form fields.</p></div>}
          {page && <div ref={pageFrame} className="pageFrame" style={{width:pageWidth+'px',minHeight:pageHeight+'px',aspectRatio:page.width+'/'+page.height}} onClick={()=>setSelected([])}>
            {pageImage?.source===state.source&&pageImage?.page===state.page ? <img className="pageImage" src={pageImage.image} alt={'PDF page '+(state.page+1)} draggable="false" /> : <div className="pageImagePlaceholder"><span className="largeSpinner"/><span>Rendering page</span></div>}
            {!state.preview&&allItems.filter((field)=>field.page===state.page).map(renderCanvasField)}
          </div>}
        </div>
        <footer className="canvasStatus"><span>{state.source ? state.preview?'Sample values shown for review':'Drag fields to move · Pull a corner to resize · Shift-click to select more' : 'Ready to open a PDF'}</span><span>{page ? Math.round(page.width)+' × '+Math.round(page.height)+' pt' : ''}</span></footer>
      </section>

      {!rightCollapsed&&<PanelSplitter side="right" value={rightWidth} min={250} max={520} onChange={setRightWidth} label="Resize Properties panel" />}
      {!rightCollapsed&&<aside className="inspector">
        <div className="inspectorTop"><span className="eyebrow">{drawer==='review'&&activeReport?'AUTOMATIC REVIEW':'PROPERTIES'}</span>{drawer==='review'&&activeReport?<button className="quietIcon" title="Close review" onClick={()=>setDrawer('')}><ChevronRight size={15}/></button>:<button className="quietIcon" title="Collapse Properties" onClick={()=>setRightCollapsed(true)}><PanelLeftClose size={15}/></button>}</div>
        {drawer==='automatic'&&<div className="inlineAuto"><span>Automatic setup</span><button onClick={runAutomatic}><Sparkles size={14}/> Analyze</button></div>}
        {renderInspector()}
      </aside>}
    </section>}

    <footer className="bottomBar"><div><span className="liveDot"/>{state.busy?'Working…':state.filename?state.dirty?'Unsaved changes':'All changes saved':'Local PDF editor'}</div><div><span>Ctrl+O Open</span><span>Ctrl+S Save</span><span>Ctrl+Z Undo</span><span>PDF content stays on this device</span></div></footer>
    {toast&&<div className="toast"><Check size={15}/>{toast}</div>}
    {updateDialog&&<UpdateDialog info={updateDialog} onClose={()=>setUpdateDialog(null)} onCheck={checkForUpdates} onDownload={()=>runUpdateAction('download')} onCancel={()=>runUpdateAction('cancel')} onInstall={()=>runUpdateAction('install')} />}
    {dragOver&&<div className="dropOverlay" onDragLeave={()=>setDragOver(false)}><div><Upload size={26}/><strong>Drop your PDF to open it</strong><span>Existing PDF form projects are supported too.</span></div></div>}
  </main>
}

function Toggle({ label, checked, onChange, disabled = false }) {
  return <label className={'toggleRow '+(disabled?'disabled':'')}><span>{label}</span><button type="button" role="switch" aria-checked={checked} disabled={disabled} className={'toggle '+(checked?'on':'')} onClick={()=>onChange(!checked)}><i/></button></label>
}

function PanelSplitter({ side, value, min, max, onChange, label }) {
  const drag = useRef(null)
  function onPointerDown(event) {
    if (event.button !== 0) return
    event.preventDefault()
    drag.current = { x: event.clientX, width: value, pointerId: event.pointerId }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function onPointerMove(event) {
    if (!drag.current || (drag.current.pointerId != null && event.pointerId !== drag.current.pointerId)) return
    const direction = side === 'left' ? 1 : -1
    onChange(Math.max(min, Math.min(max, drag.current.width + direction * (event.clientX - drag.current.x))))
  }
  function onPointerUp() { drag.current = null }
  function onKeyDown(event) {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return
    event.preventDefault()
    const amount = event.shiftKey ? 40 : 10
    if (event.key === 'Home') onChange(min)
    else if (event.key === 'End') onChange(max)
    else {
      const direction = event.key === 'ArrowRight' ? 1 : -1
      onChange(Math.max(min, Math.min(max, value + (side === 'left' ? direction : -direction) * amount)))
    }
  }
  return <div role="separator" aria-label={label} aria-orientation="vertical" aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} tabIndex={0} className={'panelSplitter '+side} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onKeyDown={onKeyDown} />
}

function UpdateDialog({ info, onClose, onCheck, onDownload, onCancel, onInstall }) {
  const status = info.status || 'checking'
  const progress = Math.max(0, Math.min(100, Number(info.progress ?? (info.totalBytes ? info.bytesDownloaded / info.totalBytes * 100 : 0))))
  const activeDownload = status === 'downloading'
  const messages = {
    checking: 'Checking the official GitHub releases…',
    available: `Version ${info.latestVersion || ''} is ready to download.`,
    current: 'You are using the latest version.',
    downloading: `Downloading ${info.assetName || 'the update'}…`,
    downloaded: 'The update is downloaded and ready to install.',
    installing: 'Installing the update. Auto PDF Form will restart when installation finishes.',
    cancelled: 'The download was cancelled. The current version is unchanged.',
    error: info.error || 'Could not check or install the update.',
  }
  return <div className="modalBackdrop" onMouseDown={(event)=>{if(event.target===event.currentTarget)onClose()}}>
    <section className="updateDialog" role="dialog" aria-modal="true" aria-labelledby="updateTitle">
      <div className="updateDialogHeader"><div><span className="eyebrow">LOCAL APP · GITHUB RELEASES</span><h2 id="updateTitle">Help &amp; updates</h2></div><button className="quietIcon" aria-label="Close" onClick={onClose}><X size={17}/></button></div>
      <p className="updateStatus" role="status">{messages[status] || info.message || 'Update status changed.'}</p>
      {info.releaseUrl&&<a className="releaseLink" href={info.releaseUrl} target="_blank" rel="noreferrer">View release notes</a>}
      {activeDownload&&<div className="downloadProgress"><div className="progressMeta"><span>{Math.round(progress)}%</span><span>{info.bytesDownloaded&&info.totalBytes?`${formatBytes(info.bytesDownloaded)} of ${formatBytes(info.totalBytes)}`:'Preparing download…'}</span></div><progress aria-label="Update download progress" max="100" value={progress}/></div>}
      {status==='available'&&info.releaseNotes&&<pre className="releaseNotes">{info.releaseNotes}</pre>}
      {status==='error'&&<p className="fieldHint">Your installed version and PDF projects were left in place.</p>}
      <div className="updateActions">
        {activeDownload?<button className="toolbarButton" onClick={onCancel}>Cancel download</button>:<button className="toolbarButton" onClick={onCheck} disabled={status==='checking'}><RotateCw size={14}/> Check again</button>}
        {status==='available'&&<button className="primaryButton" onClick={onDownload}><Download size={15}/> Download update</button>}
        {status==='downloaded'&&<button className="primaryButton" onClick={onInstall}><Download size={15}/> Install &amp; restart</button>}
      </div>
      <div className="helpNotes"><strong>Quick help</strong><span>Ctrl+mouse wheel zooms the PDF around the pointer. Normal wheel scrolls the PDF when the pointer is over the page.</span><span>Design changes are saved in your local project. Export creates a separate PDF copy.</span></div>
    </section>
  </div>
}

function formatBytes(value) {
  if (!Number.isFinite(Number(value))) return ''
  const units=['B','KB','MB','GB'];let size=Number(value),index=0
  while(size>=1024&&index<units.length-1){size/=1024;index++}
  return `${size.toFixed(index===0?0:1)} ${units[index]}`
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
