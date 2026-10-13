"""Owns a Fusion palette that hosts one HTML panel from ``web/<page>/``."""

import json
import os
import sys

import adsk.core

from ..core.constants import (
    PALETTE_HEIGHT,
    PALETTE_WIDTH,
)
from ..core.logging_setup import get_logger
from .message_bridge import MessageBridge

log = get_logger("palette")


def _process_windows():
    """``(window, rect, title)`` of each visible top-level window of this process, in the screen's own pixels (empty where not Windows)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _param):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        rect = wintypes.RECT()
        if owner.value == pid and user32.IsWindowVisible(window) and not user32.IsIconic(window) and user32.GetWindowRect(window, ctypes.byref(rect)):
            text = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, text, 256)
            found.append((window, rect, text.value))
        return True

    user32.EnumWindows(visit, 0)
    return found


def _center_new_window(before, title: str, size) -> bool:
    """Move the window that opened since ``before`` (``_process_windows()`` taken ahead) to the middle of Fusion's main window; False where
    that cannot be done. The window is the new one that is as wide as ``size`` or wider and smallest, else the one titled ``title``.

    This works in the screen's own pixels throughout, so display scaling and where the monitors sit cannot put the window off Fusion
    (``Palette.setPosition`` is in other units, which put it on another monitor).
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

    def area(w):
        return (w[1].right - w[1].left) * (w[1].bottom - w[1].top)

    now = _process_windows()
    if not now:
        return False
    main = max(now, key=area)
    seen = {w[0] for w in before}
    fresh = [w for w in now if w[0] not in seen and w[0] != main[0]]
    candidates = [w for w in fresh if w[1].right - w[1].left >= size[0] and w[1].bottom - w[1].top >= size[1]]
    target = min(candidates, key=area) if candidates else next((w for w in now if w[2] == title and w[0] != main[0]), None)
    if target is None:
        log.info("No window to centre among: %s", [(w[2], w[1].right - w[1].left, w[1].bottom - w[1].top, w[0] in seen) for w in now])
        return False
    width, height = target[1].right - target[1].left, target[1].bottom - target[1].top
    left = main[1].left + (main[1].right - main[1].left - width) // 2
    top = main[1].top + (main[1].bottom - main[1].top - height) // 2
    SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
    moved = bool(user32.SetWindowPos(target[0], None, left, top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))
    log.info("Centred the window '%s' (%sx%s) in Fusion's %s at %s,%s: %s", target[2], width, height,
             (main[1].left, main[1].top, main[1].right, main[1].bottom), left, top, moved)
    return moved


class _IncomingHandler(adsk.core.HTMLEventHandler):
    """Forwards palette messages to the MessageBridge and replies to JS."""

    def __init__(self, bridge: MessageBridge, palette_getter) -> None:
        super().__init__()
        self._bridge = bridge
        self._palette_getter = palette_getter

    def notify(self, args) -> None:
        html_args = adsk.core.HTMLEventArgs.cast(args)
        # Fusion echoes the return value of every JS handler call back to us as
        # a "response" action. It is an acknowledgement, not a request.
        if html_args.action == "response":
            return
        if html_args.action == "palette_close":   # a page's own Close button: the palette it is in is hidden, not disposed
            palette = self._palette_getter()
            if palette:
                palette.isVisible = False
            return
        response = self._bridge.dispatch(html_args.action, html_args.data)
        palette = self._palette_getter()
        if palette:
            # Reply on the same action name so JS can correlate the response.
            palette.sendInfoToHTML(html_args.action, json.dumps(response))


class PaletteHost:
    """Creates, shows and disposes one palette.

    Each panel is a folder under ``web/`` (its ``index.html`` plus its own
    scripts) that reuses ``web/shared``. Create one host per panel.
    """

    def __init__(self, ui: adsk.core.UserInterface, bridge: MessageBridge,
                 palette_id: str, title: str, page: str, docked: bool = True,
                 width: int = PALETTE_WIDTH, height: int = PALETTE_HEIGHT, close_button: bool = True) -> None:
        self._ui = ui
        self._bridge = bridge
        self._palette_id = palette_id
        self._title = title
        self._page = page
        self._docked = docked   # False: a floating window the user can place anywhere
        self._size = (width, height)
        self._close_button = close_button   # False: the page has its own way to close, so Fusion adds no bar with a Close button under it
        self._handler = None  # Kept referenced or Fusion garbage-collects it.
        self._palette = None

    def show(self) -> None:
        """Show the palette, creating it on first use."""
        palette = self._ui.palettes.itemById(self._palette_id)
        if palette is None:
            url = os.path.join(os.path.dirname(__file__), "web", self._page, "index.html")
            palette = self._ui.palettes.add(
                self._palette_id, self._title, url.replace("\\", "/"),
                True, self._close_button, True, self._size[0], self._size[1], True,
            )
            if self._docked:
                # Limit docking to the left/right edges so the panel always spans
                # the full window height, then dock it on the right by default.
                palette.dockingOption = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalOnly
                palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
            self._handler = _IncomingHandler(self._bridge, lambda: self._palette)
            palette.incomingFromHTML.add(self._handler)
            log.info("Palette created")
        self._palette = palette
        palette.isVisible = True
        log.info("Palette shown (visible=%s)", palette.isVisible)

    def show_centered(self) -> None:
        """Show the palette in the middle of Fusion's window, both ways (a floating palette otherwise opens wherever Fusion last put one).
        Windows only: elsewhere it is shown where Fusion puts it."""
        before = _process_windows()   # to tell the palette's window from the others once it opens
        self.show()
        if sys.platform != "win32":
            return
        try:
            for _ in range(5):   # the window may not exist yet: let Fusion make it
                adsk.doEvents()
                if _center_new_window(before, self._title, self._size):
                    return
        except Exception:  # only a nicety: the palette is shown wherever Fusion put it
            log.exception("Could not centre the palette")

    @property
    def visible(self) -> bool:
        """Whether the palette is open on screen."""
        palette = self._ui.palettes.itemById(self._palette_id)
        return bool(palette and palette.isVisible)

    def send(self, action: str, data: str = "{}") -> None:
        """Tell the open page something happened (its ``bridge.on(action)`` callback runs). Main thread only."""
        palette = self._ui.palettes.itemById(self._palette_id)
        if palette:
            palette.sendInfoToHTML(action, data)

    def dispose(self) -> None:
        """Remove the palette from Fusion. Safe to call repeatedly."""
        palette = self._ui.palettes.itemById(self._palette_id)
        if palette:
            palette.deleteMe()
        self._palette = None
        self._handler = None
