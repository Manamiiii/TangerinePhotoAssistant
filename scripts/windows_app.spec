# Build only explicit application resources. Never collect a workspace/config/photos.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
data = [(str(root / source), target) for source, target in [
    ("web/dist", "web/dist"), ("equipment", "equipment"), ("assets", "assets"),
    ("THIRD_PARTY_ASSETS.md", "."), ("README.md", "."),
]]
data += [(str(path), str(path.parent.relative_to(root)))
         for path in (root / "src/tangerine_photo_assistant").rglob("*.py")]
data += collect_data_files("webview")
data += [(os.environ["TANGERINE_BUILD_INFO"], ".")]
a = Analysis(
    [str(root / "scripts/desktop_entry.py")], pathex=[str(root / "src")],
    binaries=[], datas=data,
    hiddenimports=collect_submodules("uvicorn") + ["webview.platforms.winforms", "webview.platforms.edgechromium"],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "pytest", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TangerinePhotoAssistant",
          console=False, debug=False, strip=False, upx=False,
          icon=str(root / "assets/tangerine-photo-assistant.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TangerinePhotoAssistant")
