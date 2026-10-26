# Auto PDF Form — Quick start

## Install

Run `AutoPDFForm-Setup-1.0.0.exe` and choose whether to add a desktop shortcut. The installer adds a Start menu entry and includes Python, Qt, the PDF runtime, and Microsoft's signed x64 Visual C++ runtime installer; Python does not need to be installed separately. Windows may ask for administrator approval to install the Microsoft runtime if it is missing. Uninstall from Windows Settings → Apps.

For the fastest startup without installation, extract `AutoPDFForm-Portable-1.0.0.zip` and run `PDFFormStudio.exe` inside its folder. Keep the `_internal` folder next to it. The portable and single-file builds require the x64 Microsoft Visual C++ v14 runtime; install the official `vc_redist.x64.exe` included as a separate release download if Windows does not already have it.

## Open and organize a PDF

- Drop a PDF onto the app window, or choose **Open PDF…**.
- Pick a page in the left column. Search field names and filter the list by text, dropdown, checkbox or radio group.
- Select a field in the list or on the page. Drag it to move it, pull a corner to resize it, or enter exact point measurements on the right.

## Edit and export

- **Automatic** finds likely response areas. Read **Analysis report** and inspect the marked fields before exporting.
- Use **+ Text**, **+ Checkbox** or **+ Radio** to add fields. Radio options with the same group name are mutually exclusive.
- Change font, size, alignment, character limit, colors, background and border in **Field settings**.
- **Filled preview** shows a sample without replacing saved values. **Export PDF…** writes a new interactive PDF and an editable `.formstudio.json` project beside it.

Your source PDF is preserved. For repeat runs on the same blank layout, place its reviewed fillable version beside it with `_fillable` added before `.pdf`; Automatic will verify the page artwork before reusing its field map.
