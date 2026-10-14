"""Chess Coach as a desktop app: the coach server runs in the background and the
page opens in its own window (Edge WebView2) instead of the browser.
Closing the window stops the coach.

Start with:  pythonw app.py   (no console window)
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.argv.append("--no-browser")

import review  # noqa: E402  (after argv, so the server does not open a browser tab)
import webview  # noqa: E402

URL = f"http://localhost:{review.PORT}"
ICON = HERE / "icon.ico"
TITLE = "Chess Coach"
user32 = ctypes.windll.user32

# own taskbar group (so Windows shows our icon, not the Python one)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ChessCoach.App")
except Exception:
    pass


def existing_app_window():
    """The window of an already running Chess Coach app (not a console with the same title)."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def check(hwnd, _):
        title, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        user32.GetClassNameW(hwnd, cls, 256)
        if title.value == TITLE and cls.value.startswith("WindowsForms") and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(check, 0)
    return found[0] if found else None


def coach_answers():
    try:
        with urllib.request.urlopen(URL + "/api/version", timeout=2) as r:
            json.load(r)
            return True
    except Exception:
        return False


def stop_other_coach():
    """A coach started in the browser version: ask it to hand over the port to this app."""
    try:
        req = urllib.request.Request(URL + "/api/shutdown", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    for _ in range(40):
        if not coach_answers():
            return
        time.sleep(0.25)


def wait_ready(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if coach_answers():
            return True
        time.sleep(0.3)
    return False


def set_icon(window):
    """Our knight icon for the title bar and the taskbar."""
    try:
        hwnd = int(str(window.native.Handle.ToInt64()))
        for metric, kind in ((49, 0), (11, 1)):        # SM_CXSMICON -> ICON_SMALL, SM_CXICON -> ICON_BIG
            size = user32.GetSystemMetrics(metric)
            h = user32.LoadImageW(None, str(ICON), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                user32.SendMessageW(hwnd, 0x80, kind, h)                  # WM_SETICON
    except Exception:
        pass


def main():
    hwnd = existing_app_window()
    if hwnd:                                   # already open: just bring it to the front
        user32.ShowWindow(hwnd, 9)             # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return
    if not review.ENGINE.exists():
        user32.MessageBoxW(None, "The Stockfish chess engine was not found.\n\nPlease run install.bat first.", TITLE, 0x30)
        return
    if coach_answers():
        stop_other_coach()                     # this app runs its own coach from now on
    threading.Thread(target=review.main, daemon=True).start()
    if not wait_ready():
        user32.MessageBoxW(None, "The Chess Coach server did not start.", TITLE, 0x10)
        return
    window = webview.create_window(TITLE, URL, width=1500, height=940, min_size=(980, 640),
                                   background_color="#1b1a18", text_select=True)
    window.events.shown += lambda: set_icon(window)
    # keep settings like board/pieces/language between starts
    webview.start(private_mode=False, storage_path=str(HERE / "appdata"))


if __name__ == "__main__":
    main()
