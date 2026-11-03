"""Collect the runtime licenses actually installed, including native SDK notices."""
import argparse
import hashlib
import json
import sys
import zipfile
from importlib.metadata import distribution
from pathlib import Path
from urllib.request import urlopen

from ensure_nsis import compiler
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

SDK_URL = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.3856.49/microsoft.web.webview2.1.0.3856.49.nupkg"
SDK_HASH = "bc0f76eb911b569838dc4aa8f8d325269b966bedb592863d26211aef3a099f1a"


def collect(target: Path):
    root = Path(__file__).resolve().parents[1]
    target.mkdir(parents=True)
    queue = ["fastapi", "pillow", "uvicorn", "pywebview"]
    seen, inventory = set(), []
    while queue:
        name = canonicalize_name(queue.pop())
        if name in seen:
            continue
        seen.add(name)
        dist = distribution(name)
        licenses = [f for f in dist.files or [] if any(
            word in Path(str(f)).name.lower() for word in ("license", "copying"))]
        if not licenses and name != "proxy-tools":
            raise ValueError(f"Missing runtime license: {name}")
        folder = target / name
        folder.mkdir()
        if name == "proxy-tools":
            (folder / "METADATA.txt").write_text(str(dist.metadata), encoding="utf-8")
            (folder / "source-with-notice.py").write_bytes(dist.locate_file("proxy_tools/__init__.py").read_bytes())
            (folder / "Werkzeug-LICENSE.txt").write_bytes((root / "assets/licenses/Werkzeug-0.9.6-LICENSE.txt").read_bytes())
        for index, file in enumerate(licenses):
            (folder / f"{index}-{Path(str(file)).name}").write_bytes(dist.locate_file(file).read_bytes())
        inventory.append({"name": name, "version": dist.version})
        for value in dist.requires or []:
            req = Requirement(value)
            if not req.marker or req.marker.evaluate({"extra": ""}):
                queue.append(req.name)
    (target / "Python-LICENSE.txt").write_bytes((Path(sys.base_prefix) / "LICENSE.txt").read_bytes())
    for name in ("react", "react-dom", "scheduler"):
        module = root / "web/node_modules" / name
        (target / f"{name}-LICENSE.txt").write_bytes((module / "LICENSE").read_bytes())
        inventory.append({"name": name, "version": json.loads((module / "package.json").read_text())["version"]})
    sdk = root / "runtime/build-tools/webview2-sdk.nupkg"
    if not sdk.exists():
        sdk.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(SDK_URL, timeout=60) as response:
            sdk.write_bytes(response.read(50_000_001))
    if hashlib.sha256(sdk.read_bytes()).hexdigest() != SDK_HASH:
        raise ValueError("WebView2 SDK checksum mismatch")
    with zipfile.ZipFile(sdk) as archive:
        (target / "Microsoft-WebView2-LICENSE.txt").write_bytes(archive.read("LICENSE.txt"))
    nsis = compiler().parent
    (target / "NSIS-COPYING.txt").write_bytes((nsis / "COPYING").read_bytes())
    for file in (nsis.parent / "LICENSES").rglob("*"):
        if file.is_file():
            destination = target / "NSIS" / file.relative_to(nsis.parent / "LICENSES")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(file.read_bytes())
    inventory.extend([{"name": "WebView2 SDK", "version": "1.0.3856.49"},
                      {"name": "NSIS", "version": "3.13"}])
    (target / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (target / "README.txt").write_text(
        "TangerinePhotoAssistant: GPL-3.0-only. See bundled LICENSE.\n"
        "Third-party components retain their own licenses in this directory.\n"
        "Python/Pillow license files include their bundled native library notices.\n"
        "WebView2 Runtime is a separate Microsoft prerequisite, not bundled.\n"
        "PyInstaller bootloader uses GPL with a distribution exception; see PyInstaller-COPYING.txt.\n",
        encoding="utf-8")
    dist = distribution("pyinstaller")
    for file in dist.files or []:
        if Path(str(file)).name == "COPYING.txt":
            (target / "PyInstaller-COPYING.txt").write_bytes(dist.locate_file(file).read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    collect(parser.parse_args().target)
