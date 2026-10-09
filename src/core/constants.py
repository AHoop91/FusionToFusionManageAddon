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
JOBS_COMMAND_ID = "MfgToFm_PublishJobsCmd"
JOBS_PALETTE_ID = "MfgToFm_PublishJobsPalette"
JOBS_TITLE = "Job Queue"
ITEM_COMMAND_ID = "MfgToFm_OpenItemCmd"
ITEM_PALETTE_ID = "MfgToFm_ItemPalette"
ITEM_TITLE = "Fusion Manage Item"
ITEM_COMMAND_NAME = "Open Fusion Manage Item"
MENU_OPEN_COMMAND_ID = "MfgToFm_MenuOpenCmd"   # the right-click menu has commands of its own
MENU_PUBLISH_COMMAND_ID = "MfgToFm_MenuPublishCmd"

# Native ribbon. The workspace id is appended to the tab and panel ids.
RIBBON_TAB_ID = "MfgToFm_Tab"
RIBBON_TAB_NAME = "Fusion Manage"
RIBBON_PANEL_ID = "MfgToFm_SettingsPanel"
RIBBON_PANEL_NAME = "Administration"
RIBBON_PUBLISH_PANEL_ID = "MfgToFm_PublishPanel"
RIBBON_PUBLISH_PANEL_NAME = "Item"

# Workspaces that get the ribbon tab: Design and Drawing.
RIBBON_WORKSPACE_IDS = ["FusionSolidEnvironment", "FusionDrawingEnvironment"]

# Palette geometry (pixels).
PALETTE_WIDTH = 480
PALETTE_HEIGHT = 720
ITEM_WIDTH = 900
ITEM_HEIGHT = 720
JOBS_WIDTH = 440
JOBS_HEIGHT = 520
