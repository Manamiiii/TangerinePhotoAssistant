"""WebView2 origin and permission policy; no renderer-to-Python API is exposed."""
import webbrowser
from urllib.parse import urlsplit


def local_url(url: str, origin: str) -> bool:
    if any(ord(c) < 32 for c in url) or "\\" in url:
        return False
    try:
        parsed, expected = urlsplit(url), urlsplit(origin)
        return (parsed.scheme == expected.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port == expected.port and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def external_url(url: str) -> bool:
    if any(ord(c) < 32 for c in url) or "\\" in url:
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and bool(parsed.hostname) and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None
                and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
    except ValueError:
        return False


class NavigationPolicy:
    def __init__(self, origin):
        self.origin = origin

    def navigation(self, _sender, args):
        url = str(args.Uri)
        args.Cancel = url != "about:blank" and not local_url(url, self.origin)
        if args.Cancel and args.IsUserInitiated and external_url(url):
            webbrowser.open(url)

    def new_window(self, _sender, args):
        args.Handled = True
        if args.IsUserInitiated and external_url(str(args.Uri)):
            webbrowser.open(str(args.Uri))

    def download(self, _sender, args):
        url = str(args.DownloadOperation.Uri)
        if not local_url(url, self.origin) and not (url.startswith("blob:") and local_url(url[5:], self.origin)):
            args.Cancel = True
            args.Handled = True

    def attach(self, window):
        view = window.native.webview
        view.NavigationStarting += self.navigation

        def ready(sender, args):
            if not args.IsSuccess:
                return
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

            core = sender.CoreWebView2
            # Replace pywebview's unrestricted shell-browser delegation.
            core.NewWindowRequested -= window.native.browser.on_new_window_request
            core.NewWindowRequested += self.new_window
            original_download = window.native.browser.on_download_starting
            core.DownloadStarting -= original_download

            def download(sender, event):
                self.download(sender, event)
                if not event.Cancel:
                    original_download(sender, event)

            core.DownloadStarting += download

            def permission(_sender, event):
                event.State = CoreWebView2PermissionState.Deny
                event.Handled = True

            core.PermissionRequested += permission
        view.CoreWebView2InitializationCompleted += ready
