"""Archive a verified bundle with bounded retries for transient antivirus locks."""
import argparse
import time
import zipfile
from pathlib import Path


def archive(bundle, target):
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(bundle.rglob('*')):
            if not path.is_file():
                continue
            for attempt in range(5):
                try:
                    content = path.read_bytes()
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(2)
            output.writestr((Path(bundle.name) / path.relative_to(bundle)).as_posix(), content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    archive(args.bundle, args.target)
