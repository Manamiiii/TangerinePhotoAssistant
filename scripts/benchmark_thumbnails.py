"""Isolated thumbnail benchmark; never reads a configured or real photo library.

Run with --baseline-ref <commit> to compare against an existing Git revision.
All JPEGs/cache entries are synthesized in a TemporaryDirectory and removed on exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from PIL import Image

from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.thumbnails import ThumbnailCache


def measure(cache_type, repeats=3):
    measurements = {key: [] for key in ("inventory_ms", "cold_320_ms", "reuse_640_to_320_ms", "hit_ms")}
    for _ in range(repeats):
        with TemporaryDirectory(prefix="tangerine-thumbnail-benchmark-") as temporary:
            root = Path(temporary)
            originals = root / "originals"
            originals.mkdir()
            source = originals / "synthetic.jpg"
            with Image.effect_noise((4000, 3000), 90) as noise, noise.convert("RGB") as photo:
                photo.save(source, quality=95)
            settings = Settings(
                originals=originals, workspace=root / "workspace", cache_root=root / "cache",
                cache_max_size_gb=2, thumbnail_max_size_gb=1, offline_only=True, read_only=True,
                allow_move=False, allow_delete=False, allow_original_metadata_write=False,
                raw_extensions=(".raf",), exiftool=None, metadata_batch_size=8,
                burst_time_gap_seconds=3,
            )
            cache = cache_type(settings)
            for index in range(4096):
                key = hashlib.sha1(f"synthetic-cache-{index}".encode()).hexdigest()
                target = cache.root / "640" / key[:2] / f"{key}.jpg"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"inventory-only fixture")
            info = source.stat()
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            row = {"file_id": 10000, "path": str(source), "size_bytes": info.st_size,
                   "modified_ns": info.st_mtime_ns}
            start = perf_counter()
            cache.summary()
            measurements["inventory_ms"].append((perf_counter() - start) * 1000)
            with patch.object(cache, "_source", return_value=row):
                start = perf_counter()
                cache.get(10000, 320)
                measurements["cold_320_ms"].append((perf_counter() - start) * 1000)
                start = perf_counter()
                cache.get(10000, 320)
                measurements["hit_ms"].append((perf_counter() - start) * 1000)
            row = row | {"file_id": 10001}
            with patch.object(cache, "_source", return_value=row):
                cache.get(10001, 640)
                start = perf_counter()
                cache.get(10001, 320)
                measurements["reuse_640_to_320_ms"].append((perf_counter() - start) * 1000)
            assert before == hashlib.sha256(source.read_bytes()).hexdigest()
            assert source.stat().st_mtime_ns == info.st_mtime_ns
    return {key: round(median(values), 2) for key, values in measurements.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", help="Existing Git revision to compare (read-only git show)")
    arguments = parser.parse_args()
    result = {"fixture": "4000x3000 synthetic JPEG, 4096 cache entries, 3 rounds; no DB/HTTP"}
    if arguments.baseline_ref:
        repository = Path(__file__).resolve().parents[1]
        code = subprocess.run(
            ["git", "show", f"{arguments.baseline_ref}:src/tangerine_photo_assistant/thumbnails.py"],
            cwd=repository, check=True, capture_output=True, encoding="utf-8",
        ).stdout
        namespace = {"__name__": "tangerine_photo_assistant._benchmark_baseline"}
        # Explicit operator-selected repository code, never network/user photo data.
        exec(compile(code, "<git-thumbnail-baseline>", "exec"), namespace)  # noqa: S102
        result["baseline"] = measure(namespace["ThumbnailCache"])
    result["current"] = measure(ThumbnailCache)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
