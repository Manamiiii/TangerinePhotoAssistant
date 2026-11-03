"""Windows installed programs hold shared read handles during their entire lifetime."""
from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def installed_program_use():
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        yield
        return
    root = Path(sys.executable).resolve().parent.parent
    if not (root / ".tangerine-install.json").is_file():
        yield
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Maintenance takes an exclusive read/write handle. Window and backend can
    # share readers, but neither can start while files are being replaced.
    handle = kernel.CreateFileW(str(root / ".app-use.lock"), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Installation is being maintained; finish Setup and retry")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)
