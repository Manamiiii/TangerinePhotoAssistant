import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tangerine_photo_assistant.desktop_navigation import NavigationPolicy, external_url, local_url


class NavigationTests(unittest.TestCase):
    def test_origin_is_exact_and_schemes_cannot_escape(self):
        origin = 'http://127.0.0.1:18765'
        self.assertTrue(local_url(origin + '/api/library/captures', origin))
        for url in ['file:///private.txt', 'javascript:alert(1)', 'http://127.0.0.1:8765/',
                    'http://localhost:18765', 'http://127.0.0.1:18765@evil.example',
                    'http://user@127.0.0.1:18765', 'http://127.0.0.1:18765\\@evil.example',
                    'http://127.0.0.1:bad', 'http://127.0.0.1:18765\n/']:
            self.assertFalse(local_url(url, origin), url)
        self.assertTrue(external_url('https://github.com/Manamiiii/TangerinePhotoAssistant'))
        for url in ['file:///private.txt', 'javascript:alert(1)', 'ms-settings:', 'http://example.org',
                    'https://user:pass@example.org', 'https://localhost', 'https://example.org:9876',
                    'https://example.org\\anything', 'https://example.org\n']:
            self.assertFalse(external_url(url), url)

    def test_only_user_https_links_open_browser_and_foreign_downloads_are_blocked(self):
        policy = NavigationPolicy('http://127.0.0.1:18765')
        with patch('tangerine_photo_assistant.desktop_navigation.webbrowser.open') as browser:
            for url in ['file:///private.txt', 'javascript:alert(1)', 'ms-settings:']:
                event = SimpleNamespace(Uri=url, IsUserInitiated=True)
                policy.new_window(None, event)
                self.assertTrue(event.Handled)
            policy.navigation(None, SimpleNamespace(Uri='https://example.org', IsUserInitiated=False))
            browser.assert_not_called()
            event = SimpleNamespace(Uri='https://example.org', IsUserInitiated=True)
            policy.navigation(None, event)
            self.assertTrue(event.Cancel)
            browser.assert_called_once_with('https://example.org')
        event = SimpleNamespace(DownloadOperation=SimpleNamespace(Uri='https://example.org/foreign.exe'))
        policy.download(None, event)
        self.assertTrue(event.Cancel)
        event = SimpleNamespace(DownloadOperation=SimpleNamespace(Uri='blob:http://127.0.0.1:18765/export'), Cancel=False)
        policy.download(None, event)
        self.assertFalse(event.Cancel)
