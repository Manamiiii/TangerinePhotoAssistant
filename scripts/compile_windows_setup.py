"""Build Setup or an isolated test identity with the same reviewed NSIS source."""
import argparse
import os
import subprocess
from pathlib import Path

from ensure_nsis import compiler


def compile_setup(bundle, output, version, name=None, key=None):
    root = Path(__file__).resolve().parents[1]
    definitions = {"BUNDLE": str(Path(bundle).resolve()), "SETUP_OUTPUT": str(Path(output).resolve()),
                   "SETUP_VERSION": version, "PROJECT_ROOT": str(root)}
    if name:
        definitions["PRODUCT_NAME"] = name
        definitions["PRODUCT_KEY"] = key
    subprocess.run([str(compiler()), "/V2", *[f"/D{k}={v}" for k, v in definitions.items()],
                    str(root / "scripts/windows_setup.nsi")], check=True, timeout=300,
                   env={**os.environ, "NSISDIR": str(compiler().parent)},
                   creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    compile_setup(args.bundle, args.output, args.version)
