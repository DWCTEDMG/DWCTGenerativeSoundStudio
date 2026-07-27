# Compact onefile executable for the isolated modern Hugging Face Hub client.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

here = Path(os.getcwd()).resolve()
source_dir = here / "src"
if str(source_dir) not in sys.path:
    sys.path.insert(0, str(source_dir))

hiddenimports = []
datas = []
binaries = []

for package in ("huggingface_hub", "hf_xet"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

datas += copy_metadata("huggingface-hub")
datas += copy_metadata("hf-xet")

a = Analysis(
    [str(source_dir / "edmg_hf_bucket_helper" / "__main__.py")],
    pathex=[str(source_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="edmg-hf-bucket-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
