import hashlib
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import time_ns
from unittest.mock import patch

from PIL import Image

from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.thumbnails import ThumbnailCache, ThumbnailCacheUnavailable


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
    def test_large_cache_is_reused_with_orientation_and_source_unchanged(self):
        with TemporaryDirectory() as directory:
            cache, source, source_row = make_cache(Path(directory))
            exif = Image.Exif()
            exif[274] = 6
            with Image.new("RGB", (800, 600), "red") as image:
                image.save(source, exif=exif)
            before = (source.stat().st_mtime_ns, source.read_bytes())
            with patch.object(cache, "_source", side_effect=source_row):
                large = cache.get(1, 640)
                with patch.object(cache, "_render", wraps=cache._render) as render:
                    small = cache.get(1, 320)
                    self.assertEqual(render.call_args.args[0], large)
                    self.assertEqual(render.call_count, 1)
                with Image.open(small) as image:
                    self.assertEqual(image.size, (240, 320))
            self.assertEqual(before, (source.stat().st_mtime_ns, source.read_bytes()))

    def test_corrupt_large_cache_falls_back_and_small_cache_is_never_upscaled(self):
        with TemporaryDirectory() as directory:
            cache, source, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row):
                large = cache.get(1, 640)
                large.write_bytes(b"corrupt disposable thumbnail")
                with patch.object(cache, "_render", wraps=cache._render) as render:
                    small = cache.get(1, 320)
                    self.assertEqual(render.call_count, 2)
                    self.assertTrue(render.call_args.args[0].samefile(source))
                with Image.open(small) as image:
                    self.assertEqual(image.size, (320, 240))
                cache.get(2, 320)
                with patch.object(cache, "_render", wraps=cache._render) as render:
                    cache.get(2, 1280)
                    self.assertTrue(render.call_args.args[0].samefile(source))

    def test_different_source_revision_does_not_reuse_old_large_cache(self):
        with TemporaryDirectory() as directory:
            cache, source, source_row = make_cache(Path(directory))
            row = source_row(1)
            with patch.object(cache, "_source", return_value=row):
                cache.get(1, 640)
            with patch.object(cache, "_source", return_value=row | {"modified_ns": row["modified_ns"] + 1}), \
                    patch.object(cache, "_render", wraps=cache._render) as render:
                cache.get(1, 320)
                self.assertTrue(render.call_args.args[0].samefile(source))

    def test_first_thumbnail_does_not_run_maintenance(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row), \
                    patch.object(cache, "_prune", wraps=cache._prune) as prune:
                self.assertTrue(cache.get(1, 320).is_file())
                prune.assert_not_called()
                cache.prune_if_due()
                self.assertEqual(prune.call_count, 1)
                cache.prune_if_due()
                self.assertEqual(prune.call_count, 1)

    def test_maintenance_never_blocks_generation_or_queues_another_sweep(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            entered, release = Event(), Event()

            def sweep():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test maintenance was not released")
                return {"bytes_remaining": 0}

            with patch.object(cache, "_source", side_effect=source_row), \
                    patch.object(cache, "_prune", side_effect=sweep) as prune, \
                    ThreadPoolExecutor(max_workers=3) as pool:
                maintenance = pool.submit(cache.prune_if_due)
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertTrue(pool.submit(cache.get, 1, 320).result(timeout=2).is_file())
                    pool.submit(cache.prune_if_due).result(timeout=2)
                    self.assertEqual(prune.call_count, 1)
                finally:
                    release.set()
                maintenance.result(timeout=2)
            self.assertEqual(cache._created_since_prune, 1)

    def test_maintenance_failure_is_throttled_and_retries_later(self):
        with TemporaryDirectory() as directory:
            cache, _, _ = make_cache(Path(directory))
            with patch.object(cache, "_prune", side_effect=PermissionError("test")) as prune:
                cache.prune_if_due()
                cache.prune_if_due()
                self.assertEqual(prune.call_count, 1)
            cache._next_prune_at = 0
            cache.prune_if_due()
            self.assertEqual(cache._created_since_prune, 0)

    def test_repeated_maintenance_failure_bounds_growth_but_preserves_cache_hits(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row):
                existing = cache.get(1, 320)
                cache._created_since_prune = 200
                with patch.object(cache, "_prune", side_effect=PermissionError("test")):
                    cache.prune_if_due()
                self.assertEqual(cache.get(1, 320), existing)
                with patch.object(cache, "_render") as render, self.assertRaises(ThumbnailCacheUnavailable):
                    cache.get(2, 320)
                render.assert_not_called()
                cache._next_prune_at = 0
                self.assertTrue(cache.get(2, 320).is_file())
                self.assertFalse(cache._maintenance_failed)

    def test_prune_removes_only_old_cache_and_retries_recent_overage(self):
        with TemporaryDirectory() as directory:
            cache, source, source_row = make_cache(Path(directory))
            before = source.read_bytes()
            with patch.object(cache, "_source", side_effect=source_row):
                old = cache.get(1, 320)
                recent = cache.get(2, 320)
            old_time = time_ns() - 60 * 1_000_000_000
            os.utime(old, ns=(old_time, old_time))
            unrelated = cache.root / "unrelated.jpg"
            unrelated.write_bytes(b"not a cache entry")
            cache.max_bytes = 1
            cache.prune_if_due()
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(cache._created_since_prune, 100)
            os.utime(recent, ns=(old_time, old_time))
            cache._next_prune_at = 0
            cache.prune_if_due()
            self.assertFalse(recent.exists())
            self.assertEqual(cache._created_since_prune, 0)
            self.assertEqual(cache.summary()["file_count"], 0)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(unrelated.exists())

    def test_inventory_skips_directory_and_file_symlinks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache, source, source_row = make_cache(root)
            outside = root / "outside"
            outside.mkdir()
            with patch.object(cache, "_source", side_effect=source_row):
                cached = cache.get(1, 320)
            link_bucket = "ab" if cached.parent.name != "ab" else "cd"
            protected = outside / f"{link_bucket}{'0' * 38}.jpg"
            protected.write_bytes(b"do not read or delete")
            try:
                (cache.root / "320" / link_bucket).symlink_to(outside, target_is_directory=True)
                cached.with_name(f"{cached.parent.name}{'f' * 38}.jpg").symlink_to(protected)
            except OSError as error:
                self.skipTest(f"Symlinks unavailable: {error}")
            self.assertEqual(cache.summary()["file_count"], 1)
            cache.max_bytes = 1
            cache.prune()
            self.assertTrue(protected.exists())
            self.assertTrue(source.exists())

    def test_inventory_ignores_unregistered_files_and_junction_directories(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row):
                cached = cache.get(1, 320)
            cached.with_name("notes.jpg").write_bytes(b"unregistered user file")
            self.assertEqual(cache.summary()["file_count"], 1)
            actual = Path.is_junction
            with patch.object(Path, "is_junction", lambda path: path == cached.parent or actual(path)):
                self.assertEqual(cache.summary()["file_count"], 0)

    def test_prune_rechecks_access_time_after_collecting_candidates(self):
        with TemporaryDirectory() as directory:
            cache, _, source_row = make_cache(Path(directory))
            with patch.object(cache, "_source", side_effect=source_row):
                cached = cache.get(1, 320)
            old_time = time_ns() - 60 * 1_000_000_000
            os.utime(cached, ns=(old_time, old_time))
            candidates = list(cache._cache_entries())
            cache._touch(cached)
            cache.max_bytes = 1
            with patch.object(cache, "_cache_entries", return_value=iter(candidates)):
                self.assertEqual(cache.prune()["files_removed"], 0)
            self.assertTrue(cached.exists())

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
