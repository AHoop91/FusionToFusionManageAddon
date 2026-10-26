---
title: Glossary
---

# Glossary

Plain-English meanings of the terms used in this documentation. Terms are in alphabetical order.

| Term | Meaning |
|---|---|
| **APS (Autodesk Platform Services)** | Autodesk's developer platform. The add-in uses it to sign you in and to read design data. You need an **APS application** to get a Client ID. |
| **Bill of materials (BOM)** | The list of parts that make up an assembly, with how many of each. The add-in compares the design's BOM with the one in Fusion Manage. |
| **Callback URL** | The local address your browser returns to after you sign in. It is `http://localhost:8765/callback` unless you change the port. |
| **Client ID** | A code that identifies the add-in to Autodesk when you sign in. You get it from your APS application. It is not a password. |
| **Component** | A part or assembly in a Fusion design. |
| **Component linking** | An optional setting that links a Fusion Manage item to a record in the Fusion Manage components list. |
| **Details Panel** | The panel beside the BOM in the Publish panel. It shows what publishing will change for the selected component. |
| **Field mapping** | The rule that says which design property fills which Fusion Manage field. For example, *Description* fills `DESCRIPTION`. |
| **Fusion Manage** | Autodesk's cloud product lifecycle management (PLM) system. It holds the manufactured **items**. |
| **Hub** | Your organisation's workspace in Autodesk. Settings are kept per hub. |
| **Item** | A record in Fusion Manage for a manufactured part, with its own BOM, files and release workflow. |
| **Item number** | The number Fusion Manage finds an item by. It is the component's **Item Number** in the Manufacturing Data Model, and it is what the add-in matches on. A component with no item number cannot be published. |
| **Job** | One publish. The Job Queue lists jobs that are waiting, running and finished. |
| **Manufacturing Data Model (MDM)** | The description of your design that Fusion saves in the cloud: components, properties, BOM structure and thumbnails. The add-in reads it and never changes it. |
| **Part number** | What Fusion calls a component. The add-in uses it only to find the component you selected in the open design, then reads that component's item number from the Manufacturing Data Model. Fusion Manage is not searched by it. |
| **Publish** | Create or update items and BOMs in Fusion Manage from a design. Only the differences are sent. |
| **Representation** | A file that describes an item, such as a STEP file or a drawing PDF. You upload these yourself. They are never sent by a publish. |
| **Tenant** | Your company's Fusion Manage site. It is the part before `.autodeskplm360.net` in your Fusion Manage address. |
| **Where used** | The assemblies that contain a given item. |
| **Workflow** | The approval steps an item goes through in Fusion Manage, for example to release it. |
| **Workspace** | A section of Fusion Manage that holds one kind of record. This add-in works with the **Items** workspace. |
