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


def _fusion_window_rect():
    """``(left, top, right, bottom)`` of Fusion's main window in the device-independent pixels palettes are placed in (screen pixels
    divided by the display scaling), or None where it cannot be found (not Windows).

    The main window is the biggest visible window of this process: the foreground one may be a menu or a panel.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid = os.getpid()
    best = {"area": 0, "window": 0, "rect": None}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _param):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        rect = wintypes.RECT()
        if owner.value == pid and user32.IsWindowVisible(window) and not user32.IsIconic(window) and user32.GetWindowRect(window, ctypes.byref(rect)):
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            if area > best["area"]:
                best.update(area=area, window=window, rect=rect)
        return True

    user32.EnumWindows(visit, 0)
    if best["rect"] is None:
        return None
    rect = best["rect"]
    scale = (user32.GetDpiForWindow(best["window"]) or 96) / 96.0   # 2.0 at 200% scaling: palettes are placed in unscaled pixels
    return tuple(int(v / scale) for v in (rect.left, rect.top, rect.right, rect.bottom))


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
                 width: int = PALETTE_WIDTH, height: int = PALETTE_HEIGHT) -> None:
        self._ui = ui
        self._bridge = bridge
        self._palette_id = palette_id
        self._title = title
        self._page = page
        self._docked = docked   # False: a floating window the user can place anywhere
        self._size = (width, height)
        self._handler = None  # Kept referenced or Fusion garbage-collects it.
        self._palette = None

    def show(self) -> None:
        """Show the palette, creating it on first use."""
        palette = self._ui.palettes.itemById(self._palette_id)
        if palette is None:
            url = os.path.join(os.path.dirname(__file__), "web", self._page, "index.html")
            palette = self._ui.palettes.add(
                self._palette_id, self._title, url.replace("\\", "/"),
                True, True, True, self._size[0], self._size[1], True,
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

        With the window's rectangle ``(left, top, right, bottom)`` and the palette's size ``(w, h)``, all in the same pixels,
        the palette's top-left corner is ``(left + (right - left - w) / 2, top + (bottom - top - h) / 2)``.
        """
        self.show()
        try:
            rect = _fusion_window_rect()
            if rect is None or self._palette is None:
                return
            width = getattr(self._palette, "width", 0) or self._size[0]   # what Fusion made it, which can differ from what was asked
            height = getattr(self._palette, "height", 0) or self._size[1]
            left = rect[0] + (rect[2] - rect[0] - width) // 2
            top = rect[1] + (rect[3] - rect[1] - height) // 2
            self._palette.setPosition(left, top)
            log.info("Centred the palette: Fusion window %s, palette %sx%s, at %s,%s", rect, width, height, left, top)
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
