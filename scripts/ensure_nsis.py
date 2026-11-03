"""Fetch a pinned, verified portable compiler into this checkout, never the system."""
import hashlib
import tarfile
from pathlib import Path
from urllib.request import urlopen

URL = "https://github.com/electron-userland/electron-builder-binaries/releases/download/nsis%402.0.4/nsis-bundle-3.13.tar.gz"
SHA256 = "c18e9ad9684cf4c5bbd7b768cbf1b056d40771d7bd9ae1b513346452decf89d2"


def compiler():
    root = Path(__file__).resolve().parents[1] / "runtime" / "build-tools"
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "nsis-bundle-3.13.tar.gz"
    if not archive.exists():
        with urlopen(URL, timeout=60) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError("NSIS compiler archive checksum mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("NSIS compiler archive checksum mismatch")
    destination = root / "nsis-3.13"
    if not destination.exists():
        destination.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")
    return destination / "nsis-bundle" / "windows" / "makensis.exe"


if __name__ == "__main__":
    print(compiler())
