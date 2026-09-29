"""Shared constants for the MfgToFm add-in."""

ADDIN_NAME = "MfgToFm"
ADDIN_TITLE = "Fusion Manage"
SETTINGS_TITLE = "Fusion Manage Settings"
ADDIN_VERSION = "0.1.0"

# Fusion UI identifiers. Prefixed so they cannot collide with other add-ins.
COMMAND_ID = "MfgToFm_ShowPanelCmd"
SETTINGS_PALETTE_ID = "MfgToFm_SettingsPalette"
PUBLISH_COMMAND_ID = "MfgToFm_PublishItemCmd"
PUBLISH_PALETTE_ID = "MfgToFm_PublishPalette"
PUBLISH_TITLE = "Publish Item"

# Native ribbon. The workspace id is appended to the tab and panel ids.
RIBBON_TAB_ID = "MfgToFm_Tab"
RIBBON_TAB_NAME = "Fusion Manage"
RIBBON_PANEL_ID = "MfgToFm_SettingsPanel"
RIBBON_PANEL_NAME = "Settings"
RIBBON_PUBLISH_PANEL_ID = "MfgToFm_PublishPanel"
RIBBON_PUBLISH_PANEL_NAME = "Publish"

# Workspaces that get the ribbon tab: Design and Drawing.
RIBBON_WORKSPACE_IDS = ["FusionSolidEnvironment", "FusionDrawingEnvironment"]

# Palette geometry (pixels).
PALETTE_WIDTH = 480
PALETTE_HEIGHT = 720
