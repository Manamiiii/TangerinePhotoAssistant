import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from unittest.mock import patch

from PIL import Image

from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.thumbnails import ThumbnailCache


def make_cache(root):
    originals = root / "originals"
    originals.mkdir()
    settings = Settings(
        originals=originals, workspace=root / "workspace", cache_root=root / "cache",
        cache_max_size_gb=2, thumbnail_max_size_gb=1, offline_only=True, read_only=True,
        allow_move=False, allow_delete=False, allow_original_metadata_write=False,
        raw_extensions=(".raf",), exiftool=None, metadata_batch_size=8,
        burst_time_gap_seconds=3,
    )
    source = originals / "sample.jpg"
    with Image.new("RGB", (800, 600), (120, 80, 50)) as image:
        image.save(source)
    cache = ThumbnailCache(settings)

    def source_row(capture_id):
        return {"file_id": capture_id, "path": str(source), "size_bytes": source.stat().st_size,
                "modified_ns": source.stat().st_mtime_ns}

    return cache, source, source_row


class ThumbnailConcurrencyTests(unittest.TestCase):
    def test_distinct_photos_use_two_slots_and_leave_source_unchanged(self):
        with TemporaryDirectory() as directory:
            cache, source, source_row = make_cache(Path(directory))
            original = (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest())
            release, two_active, guard = Event(), Event(), Lock()
            active = peak = 0
            render = cache._render

            def controlled_render(*args):
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(active, peak)
                    if active == 2:
                        two_active.set()
                try:
                    if not release.wait(5):
                        raise TimeoutError("Test did not release thumbnail generation")
                    render(*args)
                finally:
                    with guard:
                        active -= 1

            with patch.object(cache, "_source", side_effect=source_row), \
                    patch.object(cache, "_render", side_effect=controlled_render), \
                    ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(cache.get, index, 320) for index in range(1, 9)]
                try:
                    self.assertTrue(two_active.wait(3), "Different thumbnails should not be serialized")
                finally:
                    release.set()
                paths = [future.result(timeout=5) for future in futures]
                self.assertEqual(peak, 2)
                self.assertEqual(len(set(paths)), 8)
                for path in paths:
                    with Image.open(path) as image:
                        self.assertEqual(image.size, (320, 240))
            self.assertEqual(original, (source.stat().st_mtime_ns,
                                       hashlib.sha256(source.read_bytes()).hexdigest()))

    def test_same_key_is_rendered_once_and_cached_hits_skip_decode(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row), \
                    patch.object(cache, "_render", wraps=cache._render) as render, \
                    ThreadPoolExecutor(max_workers=8) as pool:
                for capture_id in range(1, 21):
                    # Repeat first publication races (Windows may retain a
                    # long-path prefix only while a file is being created).
                    paths = list(pool.map(lambda _, current=capture_id: cache.get(current, 320), range(8)))
                    self.assertEqual(len(set(paths)), 1)
                    self.assertEqual(cache.get(capture_id, 320), paths[0])
                self.assertEqual(render.call_count, 20)

    def test_failed_render_cleans_temporary_and_can_retry(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))

            def fail(source, temporary, edge):
                temporary.write_bytes(b"partial generated file")
                raise OSError("decode failed")

            with patch.object(cache, "_source", side_effect=source_row):
                with patch.object(cache, "_render", side_effect=fail), self.assertRaises(OSError):
                    cache.get(1, 320)
                self.assertEqual(list(cache.root.rglob("*.tmp")), [])
                self.assertTrue(cache.get(1, 320).is_file())
                with self.assertRaises(ValueError):
                    cache.get(1, 999)

    def test_orientation_and_source_boundary_are_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache, source, source_row = make_cache(root)
            exif = Image.Exif()
            exif[274] = 6
            with Image.new("RGB", (800, 600)) as image:
                image.save(source, exif=exif)
            with patch.object(cache, "_source", side_effect=source_row), \
                    Image.open(cache.get(1, 320)) as image:
                self.assertEqual(image.size, (240, 320))
            outside = root / "outside.jpg"
            outside.write_bytes(b"not an allowed original")
            row = source_row(1) | {"path": str(outside)}
            with patch.object(cache, "_source", return_value=row), self.assertRaises(FileNotFoundError):
                cache.get(1, 320)


if __name__ == "__main__":
    unittest.main()
