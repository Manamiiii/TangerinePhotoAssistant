import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
from tangerine_photo_assistant.database import connect


class AlbumAssignmentCleanupTests(unittest.TestCase):
    def setup_catalog(self, c, *, automatic=True, confirmed=False):
        source = create_album(c, 'source', '纪念')['id']
        target = create_album(c, 'target', '纪念')['id']
        if automatic:
            c.execute('UPDATE events SET event_key=?,status=?,reason_json=? WHERE id=?',
                      ('dated:fixture', 'confirmed' if confirmed else 'proposed',
                       json.dumps({'method': 'directory_date_and_title'}), source))
        for index in (1, 2):
            c.execute("INSERT INTO captures(id,capture_key,parent_relative,stem,pairing_status) VALUES(?,?,'待整理/batch',?,'paired')",
                      (index, str(index), str(index)))
            c.execute('INSERT INTO event_captures VALUES(?,?,?)', (source, index, index))
        c.execute('UPDATE events SET capture_count=2 WHERE id=?', (source,))
        c.execute("INSERT INTO bursts(id,event_id,burst_key,start_at,end_at,capture_count,grouping_method) VALUES(1,?,'stable','2026-08-22','2026-08-22',2,'metadata')", (source,))
        c.executemany('INSERT INTO burst_captures VALUES(1,?,?,0)', [(1, 0), (2, 1)])
        c.execute("INSERT INTO similarity_groups(id,burst_id,group_key,capture_count,max_adjacent_hamming) VALUES(1,1,'stable',2,0)")
        c.executemany('INSERT INTO similarity_group_captures VALUES(1,?,?,0)', [(1, 0), (2, 1)])
        c.execute("INSERT INTO capture_reviews(capture_id,user_pick,user_rating,updated_at) VALUES(1,1,5,'now')")
        c.commit()
        return source, target

    def test_full_assignment_rehomes_burst_and_hides_only_empty_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp) / 'db.sqlite3')) as c:
            source, target = self.setup_catalog(c)
            groups = c.execute('SELECT * FROM similarity_groups').fetchall()
            members = c.execute('SELECT * FROM similarity_group_captures').fetchall()
            assign_captures_to_album(c, target, [1, 2])
            self.assertEqual(c.execute('SELECT event_id FROM bursts WHERE id=1').fetchone()[0], target)
            self.assertEqual(c.execute('SELECT status FROM events WHERE id=?', (source,)).fetchone()[0], 'archived')
            self.assertEqual(c.execute('SELECT * FROM similarity_groups').fetchall(), groups)
            self.assertEqual(c.execute('SELECT * FROM similarity_group_captures').fetchall(), members)
            self.assertEqual(tuple(c.execute('SELECT user_pick,user_rating FROM capture_reviews').fetchone()), (1, 5))
            assign_captures_to_album(c, target, [1, 2])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM bursts').fetchone()[0], 1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_partial_assignment_retains_source_and_does_not_move_whole_burst(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp) / 'db.sqlite3')) as c:
            source, target = self.setup_catalog(c)
            assign_captures_to_album(c, target, [1])
            self.assertEqual(c.execute('SELECT event_id FROM bursts').fetchone()[0], source)
            self.assertEqual(tuple(c.execute('SELECT capture_count,status FROM events WHERE id=?', (source,)).fetchone()), (1, 'proposed'))
            assign_captures_to_album(c, target, [2])
            self.assertEqual(c.execute('SELECT event_id FROM bursts').fetchone()[0], target)
            self.assertEqual(c.execute('SELECT status FROM events WHERE id=?', (source,)).fetchone()[0], 'archived')

    def test_user_created_or_confirmed_empty_albums_are_preserved(self):
        for automatic in (True, False):
            with self.subTest(automatic=automatic), tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp) / 'db.sqlite3')) as c:
                source, target = self.setup_catalog(c, automatic=automatic, confirmed=True)
                assign_captures_to_album(c, target, [1, 2])
                self.assertEqual(tuple(c.execute('SELECT capture_count,status FROM events WHERE id=?', (source,)).fetchone()), (0, 'confirmed'))

    def test_cleanup_failure_rolls_back_assignment_and_burst_ownership(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp) / 'db.sqlite3')) as c:
            source, target = self.setup_catalog(c)
            c.execute("CREATE TRIGGER prevent_archive BEFORE UPDATE OF status ON events WHEN NEW.status='archived' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
            c.commit()
            with self.assertRaisesRegex(Exception, 'injected failure'):
                assign_captures_to_album(c, target, [1, 2])
            self.assertEqual(c.execute('SELECT event_id FROM bursts').fetchone()[0], source)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_captures WHERE event_id=?', (source,)).fetchone()[0], 2)
