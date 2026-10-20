"""Shared constants for the MfgToFm add-in."""

ADDIN_NAME = "MfgToFm"
SETTINGS_TITLE = "Fusion Manage Settings"

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
MENU_UPLOAD_STEP_COMMAND_ID = "MfgToFm_MenuUploadStepCmd"
MENU_UPLOAD_DRAWING_COMMAND_ID = "MfgToFm_MenuUploadDrawingCmd"
EXPORT_COMMAND_ID = "MfgToFm_ExportCmd"
EXPORT_PALETTE_ID = "MfgToFm_ExportPalette"
EXPORT_TITLE = "Export"

# Native ribbon. The workspace id is appended to the tab and panel ids.
RIBBON_TAB_ID = "MfgToFm_Tab"
RIBBON_TAB_NAME = "Fusion Manage"   # the add-in's own tab, where Fusion has no tab called RIBBON_HOST_TAB_NAME
RIBBON_HOST_TAB_NAME = "Manage"   # Fusion's own tab the add-in's buttons go into
RIBBON_MERGED_PANEL_ID = "MfgToFm_ItemManagementPanel"
RIBBON_MERGED_PANEL_NAME = "Item Management"
RIBBON_EXPORT_PANEL_ID = "MfgToFm_ExportPanel"
RIBBON_EXPORT_PANEL_NAME = "Export"
RIBBON_ADMINISTRATION_NAME = "Administration"   # the submenu of Job Queue and Preferences

# Workspaces that get the ribbon tab: Design and Drawing.
RIBBON_DESIGN_WORKSPACE = "FusionSolidEnvironment"
RIBBON_DRAWING_WORKSPACE = "FusionDocumentationEnvironment"

# Palette geometry (pixels).
PALETTE_WIDTH = 600
PALETTE_HEIGHT = 720
PUBLISH_WIDTH = 1400
PUBLISH_HEIGHT = 720
ITEM_WIDTH = 900
ITEM_HEIGHT = 720
UPLOAD_PROGRESS_PALETTE_ID = "MfgToFm_UploadProgressPalette"
UPLOAD_PROGRESS_WIDTH = 460
UPLOAD_PROGRESS_HEIGHT = 190
EXPORT_WIDTH = 520
EXPORT_HEIGHT = 760
JOBS_WIDTH = 440
JOBS_HEIGHT = 520
