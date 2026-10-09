"""Owns a Fusion palette that hosts one HTML panel from ``web/<page>/``."""

import json
import os

import adsk.core

from ..core.constants import (
    PALETTE_HEIGHT,
    PALETTE_WIDTH,
)
from ..core.logging_setup import get_logger
from .message_bridge import MessageBridge

log = get_logger("palette")


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
