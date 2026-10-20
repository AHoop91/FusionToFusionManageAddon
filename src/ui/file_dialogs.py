"""Fusion's own message box, for the few things the panel cannot say itself.

Message boxes must run on Fusion's main thread, which is where palette messages are handled.
"""

import adsk.core


class FileDialogs:
    """Tell the user something through Fusion's message box."""

    def __init__(self, ui: adsk.core.UserInterface) -> None:
        self._ui = ui

    def notify(self, title: str, message: str) -> None:
        """Tell the user something in Fusion's message box."""
        self._ui.messageBox(message, title, adsk.core.MessageBoxButtonTypes.OKButtonType,
                            adsk.core.MessageBoxIconTypes.InformationIconType)
