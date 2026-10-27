"""Build portable-folder and/or single-file Windows executables with Python inside."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from PIL import Image
from PyInstaller.building import makespec

ROOT=Path(__file__).resolve().parent


def icon():
    image=Image.new('RGBA',(256,256),'#17171b')
    logo=Image.open(ROOT/'assets'/'logo-icon.png').convert('RGBA')
    logo.thumbnail((220,220),Image.Resampling.LANCZOS)
    image.alpha_composite(logo,((256-logo.width)//2,(256-logo.height)//2))
    image.save(ROOT/'app.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])


def build_ui():
    ui=ROOT/'ui'
    lock=ui/'package-lock.json'
    if not lock.is_file():raise FileNotFoundError('Run npm install in ui/ once to create package-lock.json.')
    node=shutil.which('node')
    if not node:raise FileNotFoundError('Node.js is required to build the Vite/React UI.')
    node=Path(node).resolve()
    npm_cli=node.parent/'node_modules'/'npm'/'bin'/'npm-cli.js'
    if not npm_cli.is_file():
        candidates=[Path(r'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js')]
        npm_cli=next((candidate for candidate in candidates if candidate.is_file()),None)
    if not npm_cli or not Path(str(npm_cli).replace('npm-cli.js','')).parent.exists():
        raise FileNotFoundError('Could not find the npm CLI next to Node.js.')
    if not (ui/'node_modules'/'vite'/'bin'/'vite.js').is_file():
        raise FileNotFoundError('Install frontend dependencies with npm ci in ui/ before building.')
    subprocess.run([str(node),str(npm_cli),'run','build'],cwd=ui,check=True)
    if not (ui/'dist'/'index.html').is_file():raise RuntimeError('Vite did not produce ui/dist/index.html.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['portable','standalone','both'],default='both');args=parser.parse_args()
    build_ui()
    icon()
    modes=['portable','standalone'] if args.mode=='both' else [args.mode]
    env=os.environ.copy();env['PYINSTALLER_CONFIG_DIR']=str(ROOT/'.build-cache')
    # Qt 6.11 uses Windows' ICU API. A developer PATH containing Poppler can
    # make binary analysis incorrectly collect Poppler's incompatible ICU.
    env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if 'poppler' not in p.lower() and 'libheif' not in p.lower())
    for mode in modes:
        spec=makespec.main([str(ROOT/'main.py')],name='PDFFormStudio',onefile=mode=='standalone',console=False,
            specpath=str(ROOT/'.build'/'specs'/mode),icon_file=[str(ROOT/'app.ico')],
            datas=[(str(ROOT/'app.ico'),'.'),(str(ROOT/'assets'/'logo-wordmark.png'),'assets'),
                   (str(ROOT/'assets'/'logo-icon.png'),'assets'),(str(ROOT/'ui'/'dist'),'ui/dist')],collect_all=['pypdfium2_raw'],collect_data=['pypdfium2'],
            copy_metadata=['pypdfium2','pypdf','pdfplumber'],
            excludes=['tkinter','pytest','reportlab','numpy','pandas','scipy','matplotlib','IPython','PyQt5','PyQt6','PySide2','torch','cv2'],
            shorthand_manifest=None)
        spec=Path(spec)
        content=spec.read_text(encoding='utf-8')
        content=content.replace('pyz = PYZ(a.pure)',
            "# Keep developer PDF/image runtimes and Windows API-set shims out of this PDF-only app.\n"
            "# Windows ships the API-set DLLs; Microsoft's supported VC runtime installer supplies VC runtime DLLs.\n"
            "_vc_runtime = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcruntime140_2.dll', 'vcruntime140_threads.dll', 'vcruntime140_atomic_wait.dll', 'concrt140.dll')\n"
            "a.binaries = [e for e in a.binaries if not (('poppler' in e[1].lower() and e[0].lower().endswith(('icuuc.dll', 'icuin.dll', 'icudt.dll'))) or 'libheif' in e[1].lower() or e[0].lower().startswith('api-ms-win-') or e[0].lower().split('\\\\')[-1] in _vc_runtime)]\n"
            "pyz = PYZ(a.pure)")
        spec.write_text(content,encoding='utf-8')
        command=[sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(ROOT/'release'/mode),
                 '--workpath',str(ROOT/'.build'/mode),str(spec)]
        subprocess.run(command,cwd=ROOT,env=env,check=True)
    print('Builds are in',ROOT/'release')


if __name__=='__main__':main()
