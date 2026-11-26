# Auto PDF Form Studio — Feature Gap & Usability Audit

**Reviewed:** 27 October 2026  
**Baseline:** repository at release `v1.1.0` (`d224542`)  
**Purpose:** record the visible problems in the supplied screenshots, the gaps confirmed in the code, and a prioritized, testable plan. The implementation status below supersedes the original v1.1 baseline where the code has since changed.

## Implementation status for v1.2.0

| Area | Status | What is included / remaining |
| --- | --- | --- |
| Marker appearance and fill workflow | Implemented | X/check/fill/none checkboxes; dot/fill/none radio appearance; separate Design, Fill, and PDF Preview modes; radio exclusivity. Validate across external PDF readers before relying on reader-specific visuals. |
| Canvas navigation | Implemented | Resizable/collapsible page, canvas, and properties rails; remembered layout; zoom controls and Ctrl+wheel anchored zoom; canvas wheel containment; fit width/page. Browser automation and Windows high-DPI/touchpad checks remain release QA. |
| Linked fields | Implemented | Chained links, copy/uppercase/lowercase/trim/prefix-suffix/date-part transformations, and update conditions. These are Studio project rules; arbitrary PDF readers do not execute them. |
| GitHub updater | Implemented for installed Windows copies | Stable release lookup, SHA-256 verification, progress/cancel, save prompt, Inno silent update handoff, and relaunch. Portable/one-file copies cannot replace themselves. Test on an installed clean Windows profile before treating upgrade/uninstall as certified. |
| Optional Florence vision assist | Library groundwork only | Pinned, allow-listed resumable model download and review-only OCR region inference module plus unit tests. The normal executable does not bundle the large ML runtime and there is no in-app install/progress/review workflow yet. Do not present vision analysis as available in the release UI. |
| Rewrite / secure redaction | Overlay only | Existing visible correction remains non-destructive; searchable source text can remain underneath. Secure removal is not implemented. The pinned PDF stack has no supported content-stream redaction API, and adding PyMuPDF would introduce AGPL/commercial licensing obligations requiring a deliberate project decision. |
| Save/resume fill progress, autosave, field statuses/tags, validation summary, real OCR UI | Not implemented | Still roadmap work; this release must not advertise these features. |

The full historical findings and acceptance checks below explain these limitations. “Implemented” means covered by local code and tests; it does not imply certification in every PDF reader, installer environment, or input PDF.

## Scope reviewed

The review covered the Python PDF engine and detector (`engine.py`, `auto_pdf_form.py`), the PySide6/WebChannel host (`web_editor.py`, `main.py`, `editor.py`), the React UI and its styles/tests (`ui/src`), PDF/bridge/UI tests (`tests`), build/release/installer scripts, and the user and quick-start documentation. Generated build folders, vendored libraries, and release binaries were not treated as application source.

## What the screenshots show

1. **Selection handles can look like extra form answers.** The PDF already has printed checkbox squares; selecting a nearby field adds purple resize handles and a highlighted rectangle. At a glance it is unclear which square is the actual exported checkbox, which is a printed mark, and which is only an editor handle. A selected field is visibly offset in the gender row example.
2. **The Properties sidebar has too much dead space when nothing is selected.** The empty-state message sits in a tall, narrow panel with no immediate way to add, find, or jump to a field. Resizing the side panels is not exposed in the React workspace.
3. **The user needs to choose the selected-mark style.** The screenshots show a desired X, but real forms may call for a tick, a dot, a filled square, or another simple mark. The current checkbox appearance is fixed to an X; radio uses a dot.
4. **The app needs to make page navigation and zoom predictable.** Users need the wheel over the PDF to scroll the PDF, and a deliberate modifier such as Ctrl+wheel to zoom without scrolling a surrounding panel.
5. **Automatic placement needs a reviewable confidence workflow.** Printed baselines and boxes can be detected heuristically, but scanned pages and unusual layouts need another detection path and clear progress/review controls.
6. **Visible text correction is not the same thing as editing/removing the original PDF text.** The current correction paints a patch and draws replacement wording. The original source is preserved, but underlying text in the exported PDF can remain searchable.

## Current behavior confirmed in code

- **Canvas and editor:** React canvas fields are positioned from PDF point coordinates; fields can be dragged, resized, nudged, duplicated, aligned, locked, and styled. Zoom choices are discrete, Ctrl+wheel is documented, and the canvas itself has an overflow scroller. The left rail can collapse; the React workspace uses fixed-width columns rather than draggable splitters. See `ui/src/App.jsx`, `ui/src/App.css`, and `editor.py`.
- **Selection marks:** checkbox appearances are drawn as X marks and radio appearances as circular dots in `engine.py`; the fill canvas draws an SVG X or radio dot in `ui/src/App.jsx`. Marker style is not an editable field property. The selected overlay and resize handles are a separate editor layer and can visually compete with the printed mark.
- **Form filling:** Fill & Preview provides text, multiline, dropdown, checkbox, and radio inputs on the canvas. Radio options in a group are exclusive. Field links currently copy values through text and dropdown fields while filling in Studio; they are one-way rules stored in the Studio project, not logic executed by arbitrary PDF readers. Their current values are exported.
- **Automatic setup:** `engine.py` looks at extractable PDF characters, underscore runs, slash-separated date lines, vector rules, printed square glyphs, and blank/labelled table cells. It stages results for review. Image-only/scanned pages have no OCR/vision path at this release; the README already tells users that OCR or manual placement is needed.
- **Text correction:** `Rewrite` paints a filled rectangle and draws new text inside a clipping rectangle in the output page content. It does not remove existing text operators, annotations, images, or OCR layers. The original input file is retained. This is an overlay correction, not a secure-redaction implementation.
- **Export checks:** output is reopened and checked for field names/values, widget appearances/count, and unchanged page content on pages without corrections. Tests exercise link propagation, PDF appearance markers, correction text/font, and that the source remains unchanged. They do not establish that the app has identical rendering/interaction in every third-party PDF reader.
- **Performance:** page thumbnails are requested for all pages after opening; document-page render images are cached by the bridge. Very large documents should be tested for startup latency and memory growth before claiming scalability.

## Prioritized roadmap

Priority meanings: **P0** fixes clarity or data-loss risks in normal use; **P1** major usability/quality work; **P2** optional advanced capability. Each item is a proposal, not a release promise.

### P0 — Make marks and selection unmistakable

**Problem:** the editor outline/resize handles can be mistaken for an answer mark or can obscure the printed square, as in the supplied gender-row screenshot.

**Proposed behavior:**

- Add an **Answer mark** setting for checkboxes: `X`, `check`, `filled square`, and `none`; for radio: `center dot`, `filled circle`, and `none`. Keep the default X and dot so existing projects retain their appearance.
- Draw the exact selected mark in the canvas using the same geometry, scale rules, and color as the exported PDF appearance. Avoid adding a second, differently sized symbol on top of a printed box.
- Separate **selection chrome** from the answer mark. Offer `Show editor outlines` and `Show resize handles` controls; make handles appear only for the active object, use small high-contrast corner grips, and never show them in Fill mode or exported output.
- Add a one-click **Preview marks** state that hides edit chrome and shows how selected/unselected marks will export.
- Add a quick **center/fit to printed box** command and allow keyboard arrow-key nudging at 1 pt / Shift+arrow 10 pt. Preserve undo for every adjustment.
- Add marker-type, marker-centering, screenshot-regression and export-render tests for small and large boxes, zoom levels, selected/unselected state, and dark/light PDF backgrounds.

**Acceptance checks:** for each marker style, canvas preview and exported PDF render show one centered mark, no duplicate X/box, no clipping, and no selection handles in Fill mode. Existing projects without a style setting still show X for a checkbox and dot for a radio.

### P0 — Make the Properties panel useful and resizable

**Problem:** the no-selection state in screenshot 2 consumes most of a narrow sidebar, and the sidebar width cannot be adjusted in the React workspace.

**Proposed behavior:**

- Add draggable splitters between page/field navigation, PDF canvas, and Properties. Set sensible min/max widths, keyboard-accessible splitter controls, and remember widths/collapsed state across launches.
- Add collapse/restore buttons for both sidebars. Retain an obvious handle when collapsed.
- Replace the large empty Properties state with compact actions: `Select a field`, `Add text`, `Add checkbox`, `Add radio`, `Run analysis`, and a short explanation. When multiple fields are selected, show which bulk operations are available.
- Make selected field name/type and validation errors visible without scrolling; keep long settings in a scrollable section. Use resizable/expandable panels for long link lists and automatic-analysis results.
- Add responsive layout tests at narrow and wide window sizes and a manual check that splitters do not steal PDF drag/resize gestures.

**Acceptance checks:** users can enlarge the PDF or inspector on demand, restore both rails without losing their widths, and find a useful action in the empty inspector without scrolling through blank space.

### P0 — Make PDF scroll and zoom behavior explicit

**Problem:** the canvas has its own scroll area, but wheel/trackpad routing and zoom behavior need clear, tested boundaries so the page does not unexpectedly scroll a neighboring list or panel.

**Proposed behavior:**

- Pointer over the page canvas: wheel/trackpad scrolls the PDF viewport only. Ctrl+wheel zooms around the pointer position. Shift+wheel pans horizontally. When the canvas reaches an edge, do not chain the same wheel event into a side panel.
- Pointer over a page/field list or Properties: scroll that panel only. Provide a setting for users whose mouse driver reserves Ctrl+wheel for system magnification.
- Add 10% zoom steps (40–220%), `Fit page`, `Fit width`, actual-size 100%, and remember the last zoom per workspace/document.
- Preserve the PDF point under the cursor during zoom; do not jump to the top-left. Show the current zoom as a readable percentage and allow direct entry.
- Add deterministic wheel/trackpad interaction tests and a manual Windows touchpad/mouse check. Browser-level wheel tests must cover hovering the canvas and both side panels.

**Acceptance checks:** repeated wheel over the canvas never moves the field list/Properties scroll position; Ctrl+wheel zooms in/out around the pointer; normal wheel scrolls the page; page navigation and fit controls continue to work.

### P1 — Improve field creation, labels, and placement repair

**Problem:** geometry-only detection can create a box without enough semantic context, miss unusual printed marks, or align to the wrong baseline. Scans have no optical analysis today.

**Proposed behavior:**

- Keep the fast deterministic PDF pass first: extract labels and spans, find table/rule/box geometry, identify likely answer regions, and map suggestions to nearby labels. Distinguish **detected existing fields**, **new field suggestions**, and **low-confidence/manual-review areas** in the report.
- Add confidence, reason, and source (PDF text/vector, template match, OCR, vision) to every suggestion. Let users accept, reject, edit, or bulk-accept only a selected confidence band; never silently apply low-confidence suggestions.
- Add field snapping/guides to printed square edges, baselines, table borders, and neighboring field edges. Show a magnified placement loupe while moving/resizing near a tiny mark.
- Make Automatic lazy/page-scoped by default for large PDFs, with all-pages scan as an explicit option. Render thumbnails on demand/near viewport and evict old full-size page images from cache.
- Add an optional, locally downloaded vision assist for image-only pages and ambiguous layout. It should return **candidate rectangles and OCR/region evidence**, not invent final field types or silently create controls. Reuse PDF text/vector detection when possible.
- Add a progress dialog with current page, stage (`render`, `text/vector scan`, `OCR/vision`, `review`), pages complete, cancellable work, and graceful fallback to manual placement. Keep the document usable while the worker runs.

**Acceptance checks:** each automatic suggestion is attributable and reviewable; cancellation leaves the original project untouched; reanalysis does not duplicate fields; detector coordinates are correct after zoom, crop, rotation detection, and page-size conversions; low-confidence results are never auto-applied.

### P1 — Add practical linked-field rules

**Problem:** current links copy one value verbatim and only within Studio. That is useful for repeated names but not for common derived values; cycles or conflicting paths also need an explicit policy.

**Proposed behavior:**

- Add rule types: `copy`, `uppercase`, `lowercase`, `trim`, `date-part`, and fixed-prefix/suffix. Preview the result before saving a rule.
- Present links as a small flow/map (`source → target`) with direction arrows, search, and a clear count; keep one-way links explicit. Add a conflict warning and cycle check rather than relying on traversal order.
- For dropdown targets, validate the incoming value against available options and offer a mapping table; never silently put an invalid choice into a dropdown.
- Add optional conditions (`if source is not empty`, `if target is empty`) and “clear target when source clears” as separate opt-in choices.
- Keep Studio-only behavior clearly marked. If portable PDF JavaScript is later considered, make it a separate opt-in compatibility feature and do not claim it works in all readers.
- Test cycles, chained transforms, clearing, dropdown mismatches, undo/redo, save/reopen, and exported snapshot values.

**Acceptance checks:** rule graph is deterministic and cycle-free; every transformed value has a preview; unlinking a rule leaves the typed values unchanged; third-party PDF compatibility is described accurately.

### P1 — Separate filling from sample preview

**Problem:** the current `Fill & Preview` canvas edits field values and the `Filled preview` action creates a sample PDF view. The names can make users unsure whether they are editing the design, filling a real copy, or just previewing it.

**Proposed behavior:**

- Use distinct modes: `Design form`, `Fill form`, and `Preview export`. Design edits geometry and appearance; Fill writes values; Preview shows the exact pending export without changing values.
- In Fill mode, show required/optional status, progress through pages, validation errors, clear/reset, save-progress, reopen-progress, and `Export completed form as…` to a new path. Never overwrite the blank template by default.
- Add `Previous/Next unanswered`, field focus order, keyboard navigation, and a compact form-only layout that can hide editor sidebars.
- Add persistence/recovery tests for entered values and linked values. Clearly label whether entered values are saved in the project, final PDF, or both.

**Acceptance checks:** sample preview cannot mutate saved data; fill progress survives reopening when user saves it; final filled PDF is separately named; blank source/template remains unchanged.

### P1/P2 — Correct PDF text carefully, with a real redaction mode

**Current limitation:** correction overlays do not rewrite or remove the original PDF text. Replacing a visible phrase by covering it can leave searchable/copyable old text underneath.

**Proposed staged design:**

1. **Visible correction (current):** retain as a safe, non-destructive overlay. Label it “overlay correction” in the action, project, and export report. Preview at print resolution; support multiline fit, font-size fit-to-box, fill sampling, and detect text under the patch.
2. **Replace selectable text (future):** inspect text spans/operators and font resources; remove or redact only the selected span and draw replacement text. Preserve page layout and links/annotations where possible. If an embedded/custom font or complex content stream cannot be rewritten reliably, refuse the operation and explain why.
3. **Secure redaction (future, separate explicit tool):** permanently remove covered text/vector content and affected OCR/accessibility text, then verify by text extraction and search. Warn that flattening/redaction is destructive in the new output. Keep the original untouched and export a separate copy. Detect signatures/encryption/permissions that make safe rewriting impossible.
4. **Scanned PDFs:** optionally OCR selected region to locate text; replacement may require image patching and may change image quality. Clearly label this as raster correction, retain the untouched original, and verify the output visually.

**Acceptance checks:** tests reopen output, search for the original phrase, extract replacement text, inspect annotations/content streams, compare unaffected page areas, and verify source file hashes are unchanged. A secure-redaction test must prove the original string is absent from text extraction and the output content—not merely hidden under a white rectangle.

### P2 — Optional local vision model recommendation

**Recommended design:** do **not** make a neural model a mandatory dependency. The app's existing text/vector detector is fast, deterministic, and should remain the first pass. Add an optional **Vision assist** package for scanned pages and difficult printed layouts, and always send its suggestions through the review queue.

The best capability-fit candidate found in this review is Microsoft [Florence-2-base-ft](https://huggingface.co/microsoft/Florence-2-base-ft): its model card describes a 0.23B-parameter model under MIT and supports prompt-driven image tasks; the repository is roughly 930 MB because it includes both a 463 MB SafeTensors weight file and a duplicate 464 MB PyTorch weight file. A selective downloader can avoid the duplicate `.bin`, but **~463 MB is still modest-sized, not truly tiny**. It uses custom model code and the documented example enables `trust_remote_code`; pin a reviewed commit, download only the required files, and never load a moving `main` revision blindly. Current [Florence-2 task documentation](https://huggingface.co/docs/transformers/model_doc/florence2) documents OCR-with-regions, object detection and box post-processing. [Model files and sizes](https://huggingface.co/microsoft/Florence-2-base-ft/tree/main), [license](https://huggingface.co/microsoft/Florence-2-base-ft/blob/main/LICENSE).

**Proposed implementation shape:**

- Use page text/vector analysis before vision; if the page is a normal digitally authored PDF and detection is clear, skip the model.
- Offer `Install local Vision assist` with exact download size, disk space, license, CPU/RAM note, cancel, retry/resume, cache location, and uninstall controls. The model is optional, never bundled into the regular installer.
- Pin an immutable Hub revision and allow-list the processor/config/model files plus SafeTensors only. Verify expected file hashes. Download in a worker and report total bytes, received bytes, speed, time estimate, and current file; retain resumable cache after cancellation.
- Render at bounded resolution, tile large pages with overlap so tiny boxes remain visible, run OCR-region/object-detection prompts, map boxes back to PDF points, merge overlaps, and rank candidates using nearby extracted labels/lines.
- Show progress by page/stage, elapsed time, cancel, and a review list with confidence and evidence. Let users move/resize/accept/reject candidates. Never auto-apply vision output.
- Benchmark CPU-only memory, time per page, and candidate precision/recall against representative school and generic forms before offering it by default. Keep a lightweight classic-CV checkbox/line pass as fallback.

Official sources: [Hugging Face model card](https://huggingface.co/microsoft/Florence-2-base-ft), [file listing](https://huggingface.co/microsoft/Florence-2-base-ft/tree/main), [Transformers Florence-2 tasks](https://huggingface.co/docs/transformers/model_doc/florence2), and [Hugging Face download API](https://huggingface.co/docs/huggingface_hub/guides/download). The download guide supports revision-pinned downloads and shows a progress bar for multi-file downloads. The app should use a Qt worker and relay its progress to the React view instead of freezing the editor.

### P2 — Better field discovery and navigation

- Add tags/sections (Personal details, School choices, Health, Signatures), status filters (`needs review`, `required`, `completed`, `locked`), and “jump to next unreviewed”.
- Add field rename suggestions from nearby printed labels, with user confirmation and duplicate-name detection before export.
- Show context on hover: field name, PDF coordinates, page, widget kind, group, and linked destinations.
- Allow multi-select list operations: group radio choices, lock/unlock, delete, set marker style, copy appearance, and distribute/align.
- Add page thumbnails on demand and a page overview/search for large documents.

### P2 — Preferences, safety, and interoperability

- Remember panel widths, zoom, marker style defaults, canvas overlay opacity, recent folders, and last mode. Provide reset-to-defaults.
- Add a visible **Save status** and recoverable draft autosave with explicit path/privacy controls. No cloud upload; PDFs and optional models remain local.
- Before export, show a compact validation summary: fields outside page bounds, overlaps, duplicate names, empty radio groups, invalid dropdown values, unsupported characters/fonts, hidden source text under corrections, and expected output path.
- Add interoperability fixtures and manual validation notes for Adobe Acrobat Reader, Chrome/Edge PDF viewers, and at least one open-source PDF reader. Different readers may render form appearances differently.
- Add accessibility support for keyboard focus, tab order, high-contrast selection and marker colors, scalable UI text, and screen-reader labels for canvas fields.

## Suggested delivery order

1. **v1.2 — usability and visual reliability:** marker style, accurate mark preview, clearer selection chrome, actual drag splitters, compact helpful empty inspector, explicit scroll/zoom behavior, fill/preview labels, and screenshot-level interaction tests.
2. **v1.3 — form workflow:** progress/status navigation, save/resume filling, validation summary, stronger label-to-field mapping, and safe deterministic snapping/review.
3. **v1.4 — smarter analysis:** OCR and optional local Vision assist, lazy thumbnails/page processing, progress/cancel/retry, pinned model installation, benchmark and quality report.
4. **v2 — document content editing:** selective true text replacement and separately named secure-redaction mode, both with output-level proof that the original content is actually gone when requested.

## Cross-cutting verification checklist

- Use screenshot tests for checkbox/radio marks, selection handles, overlays, and sidebar states at 50%, 100%, 150%, and 200% zoom.
- Test wheel routing, Ctrl+wheel zoom anchoring, keyboard-only splitter resizing, drag/drop, small-window layouts, and high-DPI Windows scaling.
- Test project save/reopen, undo/redo, linked-field cycles, dropdown mismatch, empty/cleared values, and export into a different PDF reader.
- Test long PDFs for open time, thumbnail rendering, UI responsiveness, and bounded image-cache memory; cancel analysis halfway and confirm no partial state is committed.
- Test scanned, searchable, hybrid, rotated, cropped, encrypted, signed, and multi-page PDFs; unsupported inputs must produce a clear reason and leave the source unchanged.
- Test real text replacement/redaction by searching extracted output text. A visual screenshot alone cannot prove that old text was removed.
- Exercise the installed and portable packages on a clean Windows profile and verify first launch, file association/drag-drop behavior, missing-runtime recovery, upgrade, uninstall, and output path permissions.

## Source references

- `engine.py`: PDF text/vector/table detection, validation, project IO, form widget creation, visible correction content stream, and export verification.
- `web_editor.py`: Qt/WebChannel API, async PDF rendering, field update/link propagation, undo/redo, automatic review, preview and export.
- `ui/src/App.jsx`: React canvas gestures, keyboard shortcuts, fill controls, inspector, links, automatic setup, selection and zoom controls.
- `ui/src/App.css` and `ui/src/index.css`: fixed workspace columns, independent scroll containers, selection/marker styles, inspector empty state, responsive breakpoints.
- `editor.py`: legacy/native Qt canvas and splitter implementation; current packaged primary UI is the WebEngine/React editor.
- `tests/test_engine.py`, `tests/test_web_editor.py`, `tests/test_gui.py`, `ui/src/App.test.jsx`: existing regression coverage; proposed checks above are additional coverage.
- `README.md`, `docs/QUICKSTART.md`, `build.py`, `package_release.py`, `installer/PDFFormStudio.iss`: user guidance and release packaging.

