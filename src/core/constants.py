"""Shared constants for the MfgToFm add-in."""

ADDIN_NAME = "MfgToFm"

# Fusion UI identifiers. Prefixed so they cannot collide with other add-ins.
COMMAND_ID = "MfgToFm_ShowPanelCmd"
SETTINGS_PALETTE_ID = "MfgToFm_SettingsPalette"
PUBLISH_PALETTE_ID = "MfgToFm_PublishPalette"
JOBS_COMMAND_ID = "MfgToFm_PublishJobsCmd"
JOBS_PALETTE_ID = "MfgToFm_PublishJobsPalette"
ITEM_COMMAND_ID = "MfgToFm_OpenItemCmd"
ITEM_PALETTE_ID = "MfgToFm_ItemPalette"
MENU_OPEN_COMMAND_ID = "MfgToFm_MenuOpenCmd"   # the right-click menu has commands of its own
MENU_PUBLISH_COMMAND_ID = "MfgToFm_MenuPublishCmd"
MENU_UPLOAD_STEP_COMMAND_ID = "MfgToFm_MenuUploadStepCmd"
MENU_UPLOAD_DRAWING_COMMAND_ID = "MfgToFm_MenuUploadDrawingCmd"
EXPORT_COMMAND_ID = "MfgToFm_ExportCmd"
EXPORT_PALETTE_ID = "MfgToFm_ExportPalette"
PRODUCT_COMMAND_ID = "MfgToFm_AssignProductCmd"
PRODUCT_PALETTE_ID = "MfgToFm_ProductPalette"
BROWSE_COMMAND_ID = "MfgToFm_BrowseProductsCmd"   # the button in Fusion's quick access toolbar, which works with no design open
BROWSE_MENU_ID = "MfgToFm_QuickAccessMenu"   # the add-in's drop-down in that toolbar, which holds the button
QUICK_ACCESS_TOOLBAR_ID = "QAT"   # Fusion's own id of that toolbar, the bar at the very top

# Native ribbon. The workspace id is appended to the tab and panel ids.
RIBBON_TAB_ID = "MfgToFm_Tab"
# The add-in's own wording for the ribbon (panels, submenu) and the palette titles is in ``ui/ui_text.py``: it follows the language, which is not known at import.
RIBBON_TAB_NAME = "Fusion Manage"   # the add-in's own tab, where Fusion has no tab called RIBBON_HOST_TAB_NAME (a product name)
RIBBON_HOST_TAB_NAME = "Manage"   # Fusion's own tab the add-in's buttons go into (Fusion's name, not the add-in's wording)
RIBBON_MERGED_PANEL_ID = "MfgToFm_ItemManagementPanel"
RIBBON_EXPORT_PANEL_ID = "MfgToFm_ExportPanel"

# Workspaces that get the ribbon tab: Design and Drawing.
RIBBON_DESIGN_WORKSPACE = "FusionSolidEnvironment"
RIBBON_DRAWING_WORKSPACE = "FusionDocumentationEnvironment"

# Palette geometry (pixels).
PALETTE_WIDTH = 600
PALETTE_HEIGHT = 720
PUBLISH_WIDTH = 1650
PUBLISH_HEIGHT = 720
ITEM_WIDTH = 900
ITEM_HEIGHT = 720
UPLOAD_PROGRESS_PALETTE_ID = "MfgToFm_UploadProgressPalette"
UPLOAD_PROGRESS_WIDTH = 460
UPLOAD_PROGRESS_HEIGHT = 190
EXPORT_WIDTH = 940
EXPORT_HEIGHT = 610
PRODUCT_WIDTH = 1100
PRODUCT_HEIGHT = 720
JOBS_WIDTH = 900
JOBS_HEIGHT = 720
