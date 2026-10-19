<a id="readme-top"></a>

> **Unofficial Project Notice**
> This project is an independent, custom-built extension for Autodesk Fusion Manage. It is not an official Autodesk product and is not supported, endorsed, or maintained by Autodesk. It integrates with Autodesk Fusion Manage through supported web and API interactions.
>
> **Disclaimer**
> This project is provided "as is" without warranties of any kind, express or implied, including but not limited to reliability, accuracy, completeness, or fitness for a particular purpose. Use of this software is at your own discretion and risk.

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/AHoop91/FusionToFusionManageAddon">
    <img src="resources/AddInIcon.svg" alt="Logo" width="200" height="200">
  </a>

  <h3 align="center">Fusion Manage Item Management</h3>

  <p align="center">
    A Fusion add-in that publishes Manufacturing Data Model items, BOMs and files into Fusion Manage.
    <br />
    <a href="https://ahoop91.github.io/FusionToFusionManageAddon/"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/AHoop91/FusionToFusionManageAddon/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/AHoop91/FusionToFusionManageAddon/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#documentation">Documentation</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->
## About The Project

![Fusion Manage ribbon tab in the Design workspace](docs/images/ribbon-design.png)

Engineering and the enterprise work to different rhythms. Engineers iterate on designs, while manufacturing, purchasing, quality and supply chain teams need a stable, controlled record of what is to be built. This add-in is the controlled bridge between the two: engineering components stay in Fusion, manufactured items live in Fusion Manage, and information crosses only when you choose to publish.

The add-in reads a design's components, properties, thumbnails and part numbers from the Manufacturing Data Model, compares them with what already exists in Fusion Manage, shows you the differences, and sends only what needs to be created or updated.

Key features:

* Sign in to Fusion Manage from Fusion with your Autodesk account (OAuth 2.0 with PKCE, no client secret)
* Create and update Fusion Manage items from your designs, matched by item number
* Map Manufacturing Data Model properties to Fusion Manage fields, with automatic unit conversion
* Compare and synchronise the design BOM with the Fusion Manage BOM
* Attach STEP files and drawing PDFs to items, manually and only when you choose to
* Item Panel to browse an item's fields, files, BOM, where-used and workflows inside Fusion
* Job Queue to track publishes that are waiting, running and finished, with retry for failed jobs
* Export and import configuration to share a setup with colleagues

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

### Built With

[![Python][python-shield]][python-url]
[![JavaScript][js-shield]][js-url]
[![HTML5][html-shield]][html-url]
[![CSS3][css-shield]][css-url]
[![Autodesk Fusion][fusion-shield]][fusion-url]
[![Autodesk Platform Services][aps-shield]][aps-url]
[![Fusion Manage][fm-shield]][fm-url]
[![MkDocs Material][mkdocs-shield]][mkdocs-url]
[![GitHub Actions][actions-shield]][actions-url]

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

* Autodesk Fusion on Windows or macOS
* A Fusion Manage tenant, and a user with permission to work in the target workspace
* An Autodesk Platform Services (APS) application of type **Desktop, Mobile, Single-Page App**, to obtain a Client ID

### Installation

1. Clone the repo
   ```sh
   git clone https://github.com/AHoop91/FusionToFusionManageAddon.git
   ```
2. In Fusion open **Utilities ▸ Add-Ins ▸ Scripts and Add-Ins**, switch to the **Add-Ins** tab and click **+** (add existing add-in).
3. Browse to the cloned folder (the one containing `Fusion Manage Item Management.py` and `Fusion Manage Item Management.manifest`).
4. Select the add-in in the list and click **Run**. Tick **Run on Startup** to load it with Fusion.
5. Create an APS application with the callback URL `http://localhost:8765/callback` and copy its Client ID.
6. Open **Manage ▸ Item Management ▸ Administration ▸ Preferences**, enter the Client ID and your tenant name, save, and click **Sign in**.

The full walkthrough, including APS application setup, is in [Installation and Authentication](https://ahoop91.github.io/FusionToFusionManageAddon/getting-started/installation/).

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- USAGE -->
## Usage

The add-in adds an **Export** panel and an **Item Management** panel to the **Manage** tab of the ribbon in the **Design** and **Drawing** workspaces. **Administration** is a submenu of **Item Management**; its buttons are pinned to the ribbon.

| Panel | Button | Purpose |
|---|---|---|
| Export | Export | Open the Export window: export the open design or drawing and attach the file to its item or component |
| Item Management | Open Fusion Manage Item | Show the item of the selected component, or of the open design or drawing |
| Item Management | Publish Fusion Manage Item (Design) | Preview and publish the open design |
| Item Management ▸ Administration | Job Queue | See publishes that are waiting, running and finished |
| Item Management ▸ Administration | Preferences | Sign in, set the connection and the workspace mapping |


The same actions are available from the right-click menu of a component.

_For more examples, please refer to the [Documentation](https://ahoop91.github.io/FusionToFusionManageAddon/)_

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- DOCUMENTATION -->
## Documentation

Full documentation is published at **[ahoop91.github.io/FusionToFusionManageAddon](https://ahoop91.github.io/FusionToFusionManageAddon/)**.

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- ROADMAP -->
## Roadmap

- [x] Publish items and BOMs from the Manufacturing Data Model
- [x] STEP file and drawing representation upload
- [x] Item Panel
- [x] Job Queue with retry
- [ ] Shared Configuration mode (read connection details from an organisation-published file)
- [ ] Support for Fusion Manage workspaces beyond **Items**

See the [open issues](https://github.com/AHoop91/FusionToFusionManageAddon/issues) for a full list of proposed features (and known issues).

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- LICENSE -->
## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/AHoop91/FusionToFusionManageAddon.svg?style=for-the-badge
[contributors-url]: https://github.com/AHoop91/FusionToFusionManageAddon/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/AHoop91/FusionToFusionManageAddon.svg?style=for-the-badge
[forks-url]: https://github.com/AHoop91/FusionToFusionManageAddon/network/members
[stars-shield]: https://img.shields.io/github/stars/AHoop91/FusionToFusionManageAddon.svg?style=for-the-badge
[stars-url]: https://github.com/AHoop91/FusionToFusionManageAddon/stargazers
[issues-shield]: https://img.shields.io/github/issues/AHoop91/FusionToFusionManageAddon.svg?style=for-the-badge
[issues-url]: https://github.com/AHoop91/FusionToFusionManageAddon/issues
[license-shield]: https://img.shields.io/github/license/AHoop91/FusionToFusionManageAddon.svg?style=for-the-badge
[license-url]: https://github.com/AHoop91/FusionToFusionManageAddon/blob/main/LICENSE
[python-shield]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
[js-shield]: https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black
[js-url]: https://developer.mozilla.org/docs/Web/JavaScript
[html-shield]: https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white
[html-url]: https://developer.mozilla.org/docs/Web/HTML
[css-shield]: https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white
[css-url]: https://developer.mozilla.org/docs/Web/CSS
[fusion-shield]: https://img.shields.io/badge/Autodesk_Fusion_API-FF6B00?style=for-the-badge&logo=autodesk&logoColor=white
[fusion-url]: https://help.autodesk.com/view/fusion360/ENU/?guid=SDK_Overview
[aps-shield]: https://img.shields.io/badge/Autodesk_Platform_Services-0696D7?style=for-the-badge&logo=autodesk&logoColor=white
[aps-url]: https://aps.autodesk.com
[fm-shield]: https://img.shields.io/badge/Fusion_Manage_API-1D4F91?style=for-the-badge&logo=autodesk&logoColor=white
[fm-url]: https://aps.autodesk.com/en/docs/fusion-manage/
[mkdocs-shield]: https://img.shields.io/badge/MkDocs_Material-526CFE?style=for-the-badge&logo=materialformkdocs&logoColor=white
[mkdocs-url]: https://squidfunk.github.io/mkdocs-material/
[actions-shield]: https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white
[actions-url]: https://github.com/features/actions
