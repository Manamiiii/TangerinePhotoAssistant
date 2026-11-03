import unittest

from tangerine_photo_assistant.desktop_prerequisites import missing_prerequisites


class PrerequisitesTests(unittest.TestCase):
    def test_missing_runtime_is_reported_before_legacy_renderer_fallback(self):
        self.assertEqual(len(missing_prerequisites(lambda *_: None)), 2)
        missing = missing_prerequisites(lambda _h, _p, name: 528040 if name == 'Release' else '0.0.0.0')
        self.assertEqual(missing, ['Microsoft Edge WebView2 Runtime'])
        self.assertEqual(missing_prerequisites(
            lambda _h, _p, name: 528040 if name == 'Release' else '140.0.0.0'), [])

    def test_framework_is_distinct_and_invalid_runtime_versions_are_rejected(self):
        self.assertEqual(missing_prerequisites(
            lambda _h, _p, name: 394801 if name == 'Release' else '140.0.0.0'),
            ['.NET Framework 4.6.2 或更新版本'])
        for version in [None, '', 'invalid', '0.0.0.0']:
            self.assertEqual(missing_prerequisites(
                lambda _h, _p, name, version=version: 528040 if name == 'Release' else version),
                ['Microsoft Edge WebView2 Runtime'])
