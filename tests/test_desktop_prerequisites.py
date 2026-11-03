import unittest

from tangerine_photo_assistant.desktop_prerequisites import missing_prerequisites


class PrerequisitesTests(unittest.TestCase):
    def test_missing_runtime_is_reported_before_legacy_renderer_fallback(self):
        self.assertEqual(len(missing_prerequisites(lambda *_: None)), 2)
        missing = missing_prerequisites(lambda _h, _p, name: 528040 if name == 'Release' else '0.0.0.0')
        self.assertEqual(missing, ['Microsoft Edge WebView2 Runtime'])
        self.assertEqual(missing_prerequisites(
            lambda _h, _p, name: 528040 if name == 'Release' else '140.0.0.0'), [])
