"""Owns a Fusion palette that hosts one HTML panel from ``web/<page>/``."""

import json
import os
from typing import Optional, Tuple

import adsk.core

from ..core.constants import (
    PALETTE_HEIGHT,
    PALETTE_WIDTH,
)
from ..core.logging_setup import get_logger
from .message_bridge import MessageBridge

log = get_logger("palette")

OPENED_ACTION = "palette_opened"   # sent to a page that is shown again; its ``bridge.on("palette_opened")`` callback runs


_last_area: Optional[Tuple[int, int, int, int]] = None   # (screen x, screen y, width, height) of Fusion's viewport, as last seen


def _viewport_area_now() -> Optional[Tuple[int, int, int, int]]:
    """The viewport's place on screen. A drawing has no active viewport, so what was seen last (in a design, or when the add-in started)
    is used then: Fusion's window is where it was. None when no viewport has been seen yet. UI thread."""
    global _last_area
    viewport = adsk.core.Application.get().activeViewport
    if viewport is not None:
        # Only the viewport's corner is converted. On a scaled display viewToScreen does not map a distance inside the
        # viewport to the same distance on screen, so the middle is found by adding half the viewport's size to the corner.
        corner = viewport.viewToScreen(adsk.core.Point2D.create(0, 0))
        _last_area = (round(corner.x), round(corner.y), viewport.width, viewport.height)
    return _last_area


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
        try:
            _viewport_area_now()   # at start-up, so a drawing opened first still has an area to centre in
        except Exception:
            log.exception("Could not read the viewport")

    def show(self) -> None:
        """Show the palette, creating it on first use.

        A docked palette opens in its dock. A floating one opens in the middle of Fusion's viewport (it would otherwise open wherever
        Fusion last put one), so every floating panel is placed the same way. An existing palette is placed while hidden and shown
        afterwards, as the API documents, so it opens in place. A new one has to be created showing (a palette created hidden loads its
        page without drawing it), so it is moved at once instead. Only the Fusion API is used, so this behaves the same on Windows and Mac.
        """
        is_new = self._ui.palettes.itemById(self._palette_id) is None
        if self._docked:
            palette = self._get_or_create(visible=True)
        else:
            palette = self._get_or_create(visible=is_new)
            try:
                self._place_in_viewport(palette)
            except Exception:  # only a nicety: the palette opens wherever Fusion puts it
                log.exception("Could not centre the palette")
        palette.isVisible = True
        log.info("Palette shown (visible=%s)", palette.isVisible)
        if not is_new:   # a page that was only hidden is still loaded: tell it it was opened again (a new page loads fresh anyway)
            palette.sendInfoToHTML(OPENED_ACTION, "{}")

    def _get_or_create(self, visible: bool):
        """The palette, created on first use (``visible`` says whether it is created showing)."""
        palette = self._ui.palettes.itemById(self._palette_id)
        if palette is None:
            url = os.path.join(os.path.dirname(__file__), "web", self._page, "index.html")
            palette = self._ui.palettes.add(
                self._palette_id, self._title, url.replace("\\", "/"),
                visible, self._close_button, True, self._size[0], self._size[1], True,
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
        return palette

    def _place_in_viewport(self, palette) -> None:
        """Move ``palette`` so its middle is the middle of the active viewport (``setPosition`` takes screen coordinates)."""
        area = _viewport_area_now()
        if area is None:
            log.info("Not centring '%s': no viewport has been seen yet", self._title)
            return
        x, y, width, height = area
        left = int(x + (width - (palette.width or self._size[0])) / 2)
        top = int(y + (height - (palette.height or self._size[1])) / 2)
        palette.setPosition(left, top)
        log.debug("Centred '%s' (%sx%s) at %s,%s in the area %sx%s at screen %s,%s",
                 self._title, palette.width, palette.height, left, top, width, height, x, y)

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
