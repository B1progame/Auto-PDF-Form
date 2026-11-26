// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App.jsx'

const initial = {
  source: 'C:/Forms/sample.pdf', filename: 'sample.pdf', page: 0,
  pages: [{ index: 0, width: 612, height: 792, fields: 5 }],
  fields: [
    { key: 'name', name: 'student_name', page: 0, rect: [80, 700, 260, 720], kind: 'text', value: '', font_size: 12, font: 'Helvetica', text_color: '#000000', background: null, border_color: '#64748b', highlight: '#b99af1', multiline: false, max_length: 0, group: '', option: 'Yes', checked: false, tooltip: 'Student name', choices: [], alignment: 0, locked: false, linked_fields: [] },
    { key: 'guardian', name: 'guardian_name', page: 0, rect: [80, 670, 260, 690], kind: 'text', value: '', font_size: 12, font: 'Helvetica', text_color: '#000000', background: null, border_color: '#64748b', highlight: '#b99af1', multiline: false, max_length: 0, group: '', option: 'Yes', checked: false, tooltip: 'Guardian name', choices: [], alignment: 0, locked: false, linked_fields: [] },
    { key: 'yes', name: 'health_choice', page: 0, rect: [100, 600, 112, 612], kind: 'radio', group: 'health', option: 'Yes', checked: false, tooltip: 'Yes', font_size: 12, locked: false },
    { key: 'no', name: 'health_choice', page: 0, rect: [160, 600, 172, 612], kind: 'radio', group: 'health', option: 'No', checked: false, tooltip: 'No', font_size: 12, locked: false },
    { key: 'agree', name: 'agreement', page: 0, rect: [200, 600, 216, 616], kind: 'checkbox', checked: false, tooltip: 'I agree', font_size: 12, marker_style: 'default', locked: false },
  ], rewrites: [], busy: false, dirty: false, preview: false, canUndo: false, canRedo: false, appVersion: '1.2.0',
}

let signal, api

beforeEach(() => {
  signal = { connect: vi.fn((fn) => { signal.handler = fn }) }
  api = Object.fromEntries(['getState','requestPage','requestThumbnail','openDialog','saveProject','exportPDF','setPage','setField','setRewrite','setFieldBatch','autoAnalyze','applyAutomatic','discardAutomatic','togglePreview','undo','redo','addField','addRewrite','templateDialog','duplicateField','deleteFields','moveFields','alignFields','chooseColor'].map((method) => [method, vi.fn(() => 'ok')]))
  api.getState.mockReturnValue(JSON.stringify(initial))
  api.event = signal
  window.qt = { webChannelTransport: {} }
  window.QWebChannel = class { constructor(_transport, ready) { ready({ objects: { pdfStudio: api } }) } }
})

afterEach(() => { cleanup(); delete window.qt; delete window.QWebChannel; delete window.__pdfStudioBackend; delete window.__pdfStudioReady })

describe('React editor integration with the local Qt bridge', () => {
  it('shows the running desktop app version from the bridge', async () => {
    render(<App />)
    expect(await screen.findByText('1.2')).toBeTruthy()
  })

  it('connects, shows the document and requests page imagery', async () => {
    render(<App />)
    expect(await screen.findByText('Page 1 of 1')).toBeTruthy()
    expect(screen.getByText('sample.pdf')).toBeTruthy()
    expect(api.requestPage).toHaveBeenCalledWith(0, 'ui')
    expect(window.__pdfStudioReady).toBe(true)
  })

  it('stages automatic edits for review before applying', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Automatic/ }))
    fireEvent.click(screen.getByRole('button', { name: /Analyze form/ }))
    expect(api.autoAnalyze).toHaveBeenCalledWith(JSON.stringify({ discover: true, scope: 'all' }))
    const report = { changes: [], review: [], pages: 1, field_widgets: 3 }
    signal.handler(JSON.stringify({ type: 'analysis', report }))
    signal.handler(JSON.stringify({ type: 'state', state: { ...initial, pending: report } }))
    expect(await screen.findByText('Suggestions are ready')).toBeTruthy()
  })

  it('keeps fill interaction exclusive to one selected radio option', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Fields/ }))
    fireEvent.click(screen.getByRole('button', { name: /health_choice.*Yes/ }))
    fireEvent.click(screen.getByRole('tab', { name: 'Content' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Fill form' }))
    expect(api.togglePreview).not.toHaveBeenCalled()
    expect(await screen.findByRole('radio', { name: 'Yes' })).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: 'Yes' }))
    expect(api.setField).toHaveBeenCalledWith('yes', JSON.stringify({ checked: true }))
    expect(api.setField).not.toHaveBeenCalledWith('no', JSON.stringify({ checked: false }))
  })

  it('filters fields and updates the inspector through the bridge', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Fields/ }))
    fireEvent.click(screen.getByRole('button', { name: /student_name/ }))
    fireEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    fireEvent.change(screen.getByLabelText('Text size'), { target: { value: '16' } })
    await waitFor(() => expect(api.setField).toHaveBeenCalledWith('name', JSON.stringify({ font_size: 16 })))
  })

  it('makes linked text targets easy to select and persists them through the bridge', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Fields/ }))
    fireEvent.click(screen.getByRole('button', { name: /student_name/ }))
    fireEvent.click(screen.getByRole('tab', { name: 'Logic' }))
    const target = screen.getByLabelText(/guardian_name/)
    fireEvent.click(target)
    expect(api.setField).toHaveBeenCalledWith('name', JSON.stringify({ linked_fields: ['guardian'] }))
  })

  it('selects and edits a printed-text correction', async () => {
    api.addRewrite.mockReturnValue('rewrite-1')
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Add field/ }))
    fireEvent.click(screen.getByRole('button', { name: /Cover & replace text/ }))
    signal.handler(JSON.stringify({ type: 'selectRewrite', key: 'rewrite-1' }))
    const rewrite = { key: 'rewrite-1', page: 0, rect: [70, 600, 250, 630], text: 'Replace this', font_size: 12, font: 'Helvetica', fill: '#ffffff', text_color: '#17212f' }
    signal.handler(JSON.stringify({ type: 'state', state: { ...initial, rewrites: [rewrite] } }))
    await waitFor(() => expect(screen.getAllByText('Replace this')).toHaveLength(2))
    fireEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    fireEvent.change(screen.getByLabelText('Text size'), { target: { value: '16' } })
    expect(api.setRewrite).toHaveBeenCalledWith('rewrite-1', JSON.stringify({ font_size: 16 }))
  })

  it('keeps Fill form interactive and separate from the static PDF preview', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('tab', { name: 'Fill form' }))
    const input = screen.getByPlaceholderText('Student name')
    fireEvent.change(input, { target: { value: 'Alex Taylor' } })
    fireEvent.blur(input)
    expect(api.setField).toHaveBeenCalledWith('name', JSON.stringify({ value: 'Alex Taylor' }))
    expect(api.togglePreview).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('tab', { name: 'Preview PDF' }))
    expect(api.togglePreview).toHaveBeenCalledTimes(1)
  })

  it('exposes the saved checkbox marker style through the field inspector', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: /Fields/ }))
    fireEvent.click(screen.getByRole('button', { name: /agreement/ }))
    fireEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    fireEvent.change(screen.getByLabelText('Selected mark'), { target: { value: 'check' } })
    expect(api.setField).toHaveBeenCalledWith('agree', JSON.stringify({ marker_style: 'check' }))
  })

  it('resizes the navigation pane from the keyboard', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    const splitter = screen.getByRole('separator', { name: 'Resize pages and fields panel' })
    expect(splitter.getAttribute('aria-valuenow')).toBe('254')
    fireEvent.keyDown(splitter, { key: 'ArrowRight' })
    expect(splitter.getAttribute('aria-valuenow')).toBe('264')
  })

  it('zooms the PDF by 10 percent around the pointer with Ctrl+wheel', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    const canvas = document.querySelector('.canvasScroll')
    const frame = document.querySelector('.pageFrame')
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 700, height: 700, right: 700, bottom: 700 })
    frame.getBoundingClientRect = () => ({ left: 40, top: 40, width: 850, height: 1100, right: 890, bottom: 1140 })
    fireEvent.wheel(canvas, { deltaY: -120, ctrlKey: true, clientX: 300, clientY: 320 })
    expect(screen.getByRole('combobox', { name: 'Zoom' }).value).toBe('110')
  })

  it('provides useful add actions in the unselected inspector', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    fireEvent.click(screen.getByRole('button', { name: 'Add checkbox' }))
    expect(api.addField).toHaveBeenCalledWith('checkbox')
  })

  it('shows updater UI only when the host exposes update APIs', async () => {
    render(<App />)
    await screen.findByText('Page 1 of 1')
    expect(screen.queryByRole('button', { name: 'Help & updates' })).toBeNull()
    cleanup()
    api.checkForUpdates = vi.fn(() => JSON.stringify({ status: 'available', latestVersion: '1.2.0', releaseNotes: 'Improvements' }))
    api.downloadUpdate = vi.fn()
    api.cancelUpdate = vi.fn()
    api.installUpdate = vi.fn()
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Help & updates' }))
    expect(screen.getByRole('dialog', { name: 'Help & updates' })).toBeTruthy()
    expect(await screen.findByText('Version 1.2.0 is ready to download.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Download update' }))
    expect(api.downloadUpdate).toHaveBeenCalledTimes(1)
  })
})
