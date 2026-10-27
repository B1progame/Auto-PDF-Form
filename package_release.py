"""Stage an organized Windows release, license notices, and the Inno Setup installer."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
PORTABLE_APP = RELEASE / "portable" / "PDFFormStudio"
STANDALONE = RELEASE / "standalone" / "PDFFormStudio.exe"


def collect_licenses() -> list[tuple[str, str, str]]:
    out = ROOT / "LICENSES" / "third-party"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    distributions = [
        "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
        "pypdf", "pdfplumber", "pdfminer.six", "pypdfium2", "Pillow",
        "cryptography", "charset-normalizer", "cffi", "pycparser",
    ]
    for name in distributions:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        version = dist.version
        license_id = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See bundled project license files"
        rows.append((name, version, license_id))
        for item in dist.files or ():
            normalized = str(item).replace("\\", "/")
            marker = ".dist-info/licenses/"
            if marker not in normalized:
                continue
            source = Path(dist.locate_file(item))
            if not source.is_file():
                continue
            relative = normalized.split(marker, 1)[1]
            if name in {"PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"} and Path(relative).name == "LicenseRef-Qt-Commercial.txt":
                continue
            target = out / f"{name}-{version}" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    if not rows:
        raise RuntimeError("No dependency license metadata was found. Use the configured build Python runtime.")
    lines = [
        "# Third-party software notices",
        "",
        "Auto PDF Form bundles the following runtime libraries. Their license texts included in `third-party/` apply to those libraries; they do not change the terms for the Auto PDF Form source code or user PDFs.",
        "",
        "| Component | Version | License metadata |",
        "| --- | --- | --- |",
    ]
    lines.extend(f"| {name} | {version} | {license_id} |" for name, version, license_id in rows)
    lines += [
        "",
        "## Qt for Python",
        "",
        f"The application dynamically loads PySide6/Qt runtime libraries. Qt for Python is offered under LGPLv3/GPLv3 and commercial terms; see the [official licensing overview](https://doc.qt.io/qtforpython-6/) and [Qt LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations). The Qt shared libraries and plugins remain replaceable in the portable/installed `_internal` directory. Matching Qt 6.11.2 and PySide 6.11.2 source archives are included as separate assets in the v{VERSION} GitHub release.",
        "",
        "This notice is not legal advice. Each bundled component retains its own copyright and license.",
    ]
    (ROOT / "LICENSES" / "THIRD-PARTY-NOTICES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def zip_tree(target: Path, files: list[Path], base: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for path in files:
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and not any(part in {"__pycache__", ".pytest_cache", ".git", "node_modules", "dist"} for part in child.parts):
                        archive.write(child, child.relative_to(base))
            elif path.is_file():
                archive.write(path, path.relative_to(base))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    if not (PORTABLE_APP / "PDFFormStudio.exe").is_file():
        raise FileNotFoundError("Build the portable folder first with `build.py --mode portable`.")
    if not STANDALONE.is_file():
        raise FileNotFoundError("Build the standalone executable first with `build.py --mode standalone`.")
    licenses = collect_licenses()
    RELEASE.mkdir(exist_ok=True)
    for name in ("README.md", "docs/QUICKSTART.md", "docs/Qt-Source-and-relink.md"):
        source = ROOT / name
        destination = PORTABLE_APP / "README.md" if name == "README.md" else PORTABLE_APP / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    license_out = PORTABLE_APP / "LICENSES"
    if license_out.exists():
        resolved = license_out.resolve()
        expected_parent = PORTABLE_APP.resolve()
        if resolved.parent != expected_parent:
            raise RuntimeError(f"Refusing to replace license directory outside the packaged app: {resolved}")
        shutil.rmtree(resolved)
    shutil.copytree(ROOT / "LICENSES", license_out)

    compiler = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if not compiler.is_file():
        raise FileNotFoundError(f"Inno Setup compiler not found: {compiler}")
    subprocess.run([str(compiler), str(ROOT / "installer" / "PDFFormStudio.iss")], cwd=ROOT, check=True)

    portable_zip = RELEASE / "portable" / f"AutoPDFForm-Portable-{VERSION}.zip"
    zip_tree(portable_zip, [PORTABLE_APP], RELEASE / "portable")
    source_items = [
        ROOT / "README.md", ROOT / "VERSION", ROOT / "main.py", ROOT / "web_editor.py", ROOT / "editor.py",
        ROOT / "engine.py", ROOT / "auto_pdf_form.py", ROOT / "build.py",
        ROOT / "package_release.py", ROOT / "requirements.txt", ROOT / ".gitignore",
        ROOT / "app.ico", ROOT / "assets", ROOT / "docs", ROOT / "installer",
        ROOT / "tests", ROOT / "LICENSES", ROOT / "ui",
    ]
    source_zip = RELEASE / "source" / f"AutoPDFForm-Source-{VERSION}.zip"
    zip_tree(source_zip, source_items, ROOT)
    setup = RELEASE / "installer" / f"AutoPDFForm-Setup-{VERSION}.exe"
    if not setup.is_file():
        raise FileNotFoundError(f"Inno Setup did not create the installer: {setup}")
    vc_runtime = RELEASE / "installer" / "vc_redist.x64.exe"
    if not vc_runtime.is_file():
        raise FileNotFoundError("Download the official Microsoft x64 VC++ redistributable to release/installer/vc_redist.x64.exe before packaging.")

    release_notes = RELEASE / f"AutoPDFForm-v{VERSION}-RELEASE-NOTES.md"
    release_notes.write_text(
        f"# Auto PDF Form {VERSION}\n\n"
        "Native Windows PDF form editor with a Vite/React interface hosted in PySide6 WebEngine, automatic field analysis, a drag-and-resize canvas, searchable field categories, and a dark gray/purple interface. Includes Python and the PDF/Qt runtime.\n\n"
        "## Downloads\n\n"
        f"- `AutoPDFForm-Setup-{VERSION}.exe` — Inno Setup installer; Start menu entry and optional desktop shortcut.\n"
        f"- `AutoPDFForm-Portable-{VERSION}.zip` — fast-launch folder build. Extract the whole folder.\n"
        f"- `PDFFormStudio.exe` — single-file build; first launch extracts its runtime.\n"
        f"- `AutoPDFForm-Source-{VERSION}.zip` — Python source, tests, docs and build scripts.\n\n"
        "The Inno installer includes Microsoft's signed x64 VC++ runtime installer and runs it only if that runtime is missing. Portable and standalone downloads require the separate `vc_redist.x64.exe` asset. The matching Qt 6.11.2 and PySide 6.11.2 source archives are supplied as separate release assets with verified SHA-256 hashes. See `Qt-Source-and-relink.md` in the installer and source archive.\n\n"
        "Automatic field finding is heuristic for unfamiliar layouts; review the analysis report before sharing the resulting form. The matching school-form template is checked against every page before its map is reused.\n",
        encoding="utf-8",
    )
    sums = []
    qt_sources = RELEASE / "source" / "third-party"
    source_assets = [qt_sources / "qt-everywhere-src-6.11.2.tar.xz", qt_sources / "pyside-setup-everywhere-src-6.11.2.tar.xz"]
    source_hashes = {
        source_assets[0]: "6DCFBCA271D76A6502741A2C0DC6FC98EF7DD0B7B4CFD0ABCEBB285A86A26F33",
        source_assets[1]: "CBA47EFBAAD1BEDD529725CBC14E21F156C7A19366F07B3EDFBB076FFD7AFDF8",
    }
    for asset in (setup, portable_zip, STANDALONE, source_zip, vc_runtime, *source_assets):
        if not asset.is_file():
            raise FileNotFoundError(f"Required release asset is missing: {asset}")
        digest = sha256_file(asset)
        if asset in source_hashes and digest != source_hashes[asset]:
            raise RuntimeError(f"Official Qt source checksum mismatch: {asset.name}")
        sums.append(f"{digest}  {asset.name}")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii")
    print("Staged release files:")
    for asset in (setup, portable_zip, STANDALONE, source_zip, vc_runtime, *source_assets, release_notes):
        print(f"{asset}  ({asset.stat().st_size:,} bytes)")
    print(f"Bundled dependency notices for {len(licenses)} distributions.")


if __name__ == "__main__":
    main()
