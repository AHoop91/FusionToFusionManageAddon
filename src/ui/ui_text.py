"""The add-in's own wording in Fusion's windows and ribbon, in the language the user chose.

Each is a function, not a constant: the language is set when the add-in starts, after this module is imported. Ribbon names, tooltips and
palette titles are fixed by Fusion once built, so they follow a change of language after Fusion is restarted.
"""

from ..core.i18n import t


def settings_title() -> str:
    return t("app.settings_title")


def publish_title() -> str:
    return t("app.publish_title")


def jobs_title() -> str:
    return t("app.jobs_title")


def item_title() -> str:
    return t("app.item_title")


def item_command_name() -> str:
    """The name of the command that opens the item, and the title of the message boxes of the item's commands."""
    return t("app.item_open_name")


def export_title() -> str:
    return t("app.export_title")


def products_title() -> str:
    """The name of the View product portfolio command and the title of its window."""
    return t("app.products_title")


def products_tooltip() -> str:
    return t("app.products_tooltip")


def browse_title() -> str:
    """The name of the Browse Product Portfolio button in the quick access toolbar."""
    return t("app.browse_title")


def browse_tooltip() -> str:
    return t("app.browse_tooltip")


def upload_title() -> str:
    return t("app.upload_title")


def ribbon_merged_panel_name() -> str:
    return t("app.ribbon_panel_item_management")


def ribbon_administration_name() -> str:
    """The submenu of Job Queue and Settings."""
    return t("app.ribbon_administration")


def jobs_tooltip() -> str:
    return t("app.jobs_tooltip")


def publish_tooltip() -> str:
    return t("app.publish_tooltip")


def upload_drawing_name() -> str:
    return t("app.export_pdf_label")


def upload_drawing_tooltip() -> str:
    return t("app.upload_drawing_tooltip")


def menu_open_tooltip() -> str:
    return t("app.menu_open_tooltip")


def menu_publish_name() -> str:
    return t("app.menu_publish_name")


def export_step_name() -> str:
    return t("app.export_step_name")


def export_step_tooltip() -> str:
    return t("app.export_step_tooltip")


def ribbon_open_tooltip() -> str:
    return t("app.ribbon_open_tooltip")


def ribbon_export_tooltip() -> str:
    return t("app.ribbon_export_tooltip")


def preferences_name() -> str:
    return t("app.ribbon_preferences_name")


def preferences_tooltip() -> str:
    return t("app.ribbon_preferences_tooltip")


def start_failed(details: str) -> str:
    """What the message box says when the add-in cannot start."""
    return t("app.start_failed", details=details)
