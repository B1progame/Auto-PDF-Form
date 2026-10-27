// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App.jsx'

const initial = {
  source: 'C:/Forms/sample.pdf', filename: 'sample.pdf', page: 0,
  pages: [{ index: 0, width: 612, height: 792, fields: 3 }],
  fields: [
    { key: 'name', name: 'student_name', page: 0, rect: [80, 700, 260, 720], kind: 'text', value: '', font_size: 12, font: 'Helvetica', text_color: '#000000', background: null, border_color: '#64748b', highlight: '#b99af1', multiline: false, max_length: 0, group: '', option: 'Yes', checked: false, tooltip: 'Student name', choices: [], alignment: 0, locked: false, linked_fields: [] },
    { key: 'guardian', name: 'guardian_name', page: 0, rect: [80, 670, 260, 690], kind: 'text', value: '', font_size: 12, font: 'Helvetica', text_color: '#000000', background: null, border_color: '#64748b', highlight: '#b99af1', multiline: false, max_length: 0, group: '', option: 'Yes', checked: false, tooltip: 'Guardian name', choices: [], alignment: 0, locked: false, linked_fields: [] },
    { key: 'yes', name: 'health_choice', page: 0, rect: [100, 600, 112, 612], kind: 'radio', group: 'health', option: 'Yes', checked: false, tooltip: 'Yes', font_size: 12, locked: false },
    { key: 'no', name: 'health_choice', page: 0, rect: [160, 600, 172, 612], kind: 'radio', group: 'health', option: 'No', checked: false, tooltip: 'No', font_size: 12, locked: false },
  ], rewrites: [], busy: false, dirty: false, preview: false, canUndo: false, canRedo: false,
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
    fireEvent.click(screen.getByRole('tab', { name: /Fill & preview/ }))
    expect(await screen.findByRole('button', { name: 'Yes' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
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
})
