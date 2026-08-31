"""Generate package identity and an explicit inventory; no user data is collected."""
import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from tangerine_photo_assistant.build_info import build_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["identity", "manifest"])
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    if args.mode == "identity":
        value = {**build_info(), "built_at": datetime.now(UTC).isoformat()}
        target = args.target
    else:
        value = json.loads((args.target / "_internal/build-info.json").read_text(encoding="utf-8"))
        value.update(format=1, app_id="tangerine-photo-assistant", files=[])
        for path in sorted(args.target.rglob("*")):
            if path.is_symlink() or path.is_junction():
                raise ValueError("Package must not contain filesystem links")
            if path.is_file():
                with path.open("rb") as source:
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                value["files"].append({"path": path.relative_to(args.target).as_posix(), "sha256": checksum})
        target = args.target / "package-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)


if __name__ == "__main__":
    main()
