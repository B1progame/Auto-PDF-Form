# Qt source and relinking

This Windows build contains the Qt for Python 6.11.2 runtime. Its Qt shared libraries are dynamically loaded from the installed `PDFFormStudio/_internal` directory. They are not modified by Auto PDF Form, and there is no signature or runtime lock that prevents replacing them.

The matching full Qt 6.11.2 source archive and PySide setup source archive are provided as separate assets on the [v1.1.0 GitHub release](https://github.com/B1progame/Auto-PDF-Form/releases/tag/v1.1.0):

- `qt-everywhere-src-6.11.2.tar.xz`
- `pyside-setup-everywhere-src-6.11.2.tar.xz`

The archives were downloaded from Qt's official release servers; their SHA-256 digests are recorded in the release's `SHA256SUMS.txt` manifest. The matching source is distributed for users who need to study, modify or rebuild the libraries. To replace the Qt runtime in an installed copy, close the app and replace the corresponding Qt DLLs in `{app}\_internal` with compatible rebuilt libraries; the portable build has the same layout. Keep the Python extension modules and Qt libraries ABI-compatible. The one-file executable is less convenient to modify; use the installer or portable build for library replacement.

Qt's build requirements, exact build steps and license conditions are maintained in the corresponding source archives and the [Qt for Python build-from-source guide](https://doc.qt.io/qtforpython-6/building_from_source/index.html). See `LICENSES/THIRD-PARTY-NOTICES.md` and the included LGPL/GPL license texts. Qt's official [LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) apply to the relevant Qt components.
