---
title: Installation and Authentication
---

# Installation and Authentication

## Install the add-in

1. Get the add-in folder (the one containing `MfgToFm.py` and `MfgToFm.manifest`).
2. In Fusion open **Utilities ▸ Add-Ins ▸ Scripts and Add-Ins**, switch to the **Add-Ins** tab, click **+** (add existing add-in) and browse to the folder.
3. Select **MfgToFm** in the list and click **Run**. Tick **Run on Startup** if you want it to load with Fusion.

The manifest declares support for Windows and macOS. Once running, a **Fusion Manage** tab appears in the Design and Drawing workspaces.

## Connection settings

Open **Fusion Manage ▸ Administration ▸ Preferences**. Signed out, the panel shows **Sign in to Fusion Manage** with a **Connection settings** link. Once signed in, the same fields are on the **Connection** tab.

| Setting | Meaning |
|---|---|
| **Client ID** | The client ID of your APS application. |
| **Tenant** | Your Fusion Manage tenant name, for example `mycompany`. The add-in talks to `https://<tenant>.autodeskplm360.net`. |
| **Callback port** | Local port that receives the sign-in redirect. Default `8765`; allowed range 1024–65535. |
| **Scopes** | Space-separated. Default `data:read data:write data:search`. |

The panel shows the callback URL to register on your APS application. With the default port it is:

```
http://localhost:8765/callback
```

A Client ID, a Tenant, a valid port and at least one scope are required before you can sign in.

### Registering the APS application

You need an application registered with Autodesk Platform Services (APS) to obtain a Client ID. See the [APS documentation](https://aps.autodesk.com/) for how to create one.

!!! info "What the add-in requires of the APS application"
    - It signs in with the OAuth 2.0 authorization-code flow with PKCE and **sends no client secret**.
    - The callback URL shown above must be registered exactly.
    - The `data:read`, `data:write` and `data:search` scopes must be allowed.

## Signing in

1. In **Preferences**, click **Sign in**.
2. Your browser opens the Autodesk sign-in page. Sign in and approve access.
3. The browser shows **Signed in** and tells you to return to Fusion.
4. Back in Fusion the panel unlocks its tabs.

Sign-in waits up to 180 seconds; click **Cancel** to abort it sooner. The add-in listens on `127.0.0.1` only, for that one redirect, and checks the `state` value to reject forged redirects. Access tokens are refreshed automatically shortly before they expire.

### Where tokens are kept

Tokens are never written to the configuration file or to logs.

| Platform | Storage |
|---|---|
| Windows | Encrypted with Windows DPAPI for your user account, in a file under `%LOCALAPPDATA%\MfgToFm`. |
| macOS | Your login Keychain. |

### Signing out

Use the account menu in the panel header. This removes the stored tokens for the current Client ID.

## Configuration modes

On the **General** tab:

- **Local Configuration**: you enter the connection details on the **Connection** tab. They are stored in your user profile on this machine.
- **Shared Configuration**: *coming soon*. It will read connection details from a file published by your organisation. The option is shown but disabled.

## Export and import your configuration

On the **Profile** tab, **Export…** saves your mode, connection details, workspace IDs and field mappings to a JSON file, and **Import…** loads one. This is the easiest way to give colleagues a standard setup.

- Tokens are never included in an export.
- An import replaces your current settings and is validated like a manual save. If the file is invalid, nothing changes.
- Files over 1 MB, files that are not valid JSON, and files that are not an MfgToFm configuration are rejected.

## Permissions in Fusion Manage

Signing in does not grant access by itself. Before publishing, the add-in checks that your Fusion Manage user holds these permissions in the Items workspace: View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. Viewing an item needs only View Items. If one is missing, the message names it.
