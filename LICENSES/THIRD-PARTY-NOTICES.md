# Third-party software notices

Auto PDF Form bundles the following runtime libraries. Their license texts included in `third-party/` apply to those libraries; they do not change the terms for the Auto PDF Form source code or user PDFs.

| Component | Version | License metadata |
| --- | --- | --- |
| PySide6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Essentials | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Addons | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| shiboken6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pypdf | 6.10.0 | BSD-3-Clause |
| pdfplumber | 0.11.9 | See bundled project license files |
| pdfminer.six | 20251230 | MIT |
| pypdfium2 | 5.14.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| Pillow | 12.3.0 | MIT-CMU |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| charset-normalizer | 3.5.1 | MIT |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.0 | BSD-3-Clause |

## Qt for Python

The application dynamically loads PySide6/Qt runtime libraries. Qt for Python is offered under LGPLv3/GPLv3 and commercial terms; see the [official licensing overview](https://doc.qt.io/qtforpython-6/) and [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations). The Qt shared libraries and plugins remain replaceable in the portable/installed `_internal` directory. Matching Qt 6.11.2 and PySide 6.11.2 source archives are included as separate assets in the v1.1.0 GitHub release.

This notice is not legal advice. Each bundled component retains its own copyright and license.
