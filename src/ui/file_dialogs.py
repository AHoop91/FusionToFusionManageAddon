"""Native Fusion open/save file dialogs.

Wraps ``ui.createFileDialog`` so actions can ask for a path without touching
the Fusion API. Dialogs must run on Fusion's main thread, which is where
palette messages are handled.
"""

from typing import Optional

import adsk.core

JSON_FILTER = "JSON files (*.json)"


class FileDialogs:
    """Ask the user for a file path through Fusion's own dialogs."""

    def __init__(self, ui: adsk.core.UserInterface) -> None:
        self._ui = ui

    def choose_save_path(self, title: str, default_name: str) -> Optional[str]:
        """Return a chosen ``.json`` path, or None if the user cancelled."""
        dialog = self._ui.createFileDialog()
        dialog.title = title
        dialog.filter = JSON_FILTER
        dialog.initialFilename = default_name
        if dialog.showSave() != adsk.core.DialogResults.DialogOK:
            return None
        path = dialog.filename
        return path if path.lower().endswith(".json") else path + ".json"

    def choose_open_path(self, title: str) -> Optional[str]:
        """Return an existing ``.json`` path, or None if the user cancelled."""
        dialog = self._ui.createFileDialog()
        dialog.title = title
        dialog.filter = JSON_FILTER
        dialog.isMultiSelectEnabled = False
        if dialog.showOpen() != adsk.core.DialogResults.DialogOK:
            return None
        return dialog.filename
