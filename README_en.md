> German version: see [README.md](README.md)
> # Import LandXML Tools (QGIS)...

QGIS Processing scripts to bring survey data — especially from Trimble Access — into QGIS quickly and robustly, without DXF detours and without overwrite prompts.

> Why? The DXF writers in Trimble Access / Trimble ASCII File Generator are often cumbersome for quick handovers. This repo focuses on LandXML/CSV → QGIS and then writes clean GeoPackage (GPKG) outputs.

---

## Tools

- **Layer → GeoPackage (new & timestamp)**  
  Exports selected vector layers into a new GeoPackage.  
  Filename gets a timestamp (`…__YYYY-mm-dd_HHMM.gpkg`).  
  No overwrite prompts.

- **Layer → GeoPackage (new)**  
  Same as above, without the timestamp. Still always creates a new file.

- **LandXml2QGIS**  
  Helpers around LandXML (points / breaklines / faces → layers).  
  Note: LandXML may be interpreted slightly differently by QGIS/OGR; these scripts provide fixed layer names and Z support.

Find the tools in QGIS under **Processing → Scripts → Import LandXml**.

---

## Requirements

- QGIS 3.40 (tested)  
- Python 3.12 (bundled)  
- GDAL 3.11+

---

## Installation

1. **Copy scripts**  
   Place the files from `scripts/` into: %APPDATA%\QGIS\QGIS3\profiles<YOUR_PROFILE>\processing\scripts\
   (Replace `<YOUR_PROFILE>` with your profile name. Create folders if they don’t exist.)

2. **Reload Processing**  
- Easiest: restart QGIS.  
- Alternative without restart: **Plugins → Manage and Install Plugins… → “Processing”** temporarily disable and enable again.  
- Pro option (Python console):
  ```python
  from qgis.core import QgsApplication
  prov = QgsApplication.processingRegistry().providerById('script')
  if prov:
      prov.refreshAlgorithms()
      print("Script provider reloaded.")
  ```

3. The tools will appear under **Processing → Scripts → Import LandXml**.

---

## Typical workflow

1. Export **coordinates, lines, polygons, breaklines or faces**  
(e.g. LandXML from Trimble Access or another source).
2. Load into QGIS (split LandXML into layers: points/breaklines/faces).
3. Run **Layer → GeoPackage (new & timestamp)**, choose a target path → **Run**.  
- Output: `…__YYYY-mm-dd_HHMM.gpkg` (on collision: `…__1.gpkg`, `…__2.gpkg` …)  
- Geometry column = `geom`, spatial index enabled

> Note: CSV/WKT support (points, lines via WKT or “points to paths”) is intended but will be documented later after testing.

---

## Design choices

- Safety & traceability: always a new GPKG (optional timestamp). No overwrite dialogs.  
- Clean geometry column: always `geom`, plus spatial index.  
- Z values: preserved where available.  
- CRS: no automatic reprojection — set the correct CRS on import (often EPSG:25832).

---

## Troubleshooting

- Invisible layer / warning icon: right-click → *Zoom to layer*. Check project CRS (OTF on, proper EPSG). Try simple styling.  
- GPKG looks empty: open attribute table; if empty, fix the source (filters? wrong CRS?).  
- Windows crash on overwrite: avoided by always writing new files.

---

## Roadmap

- **Separate “Append (with schema alignment)” tool**  
Planned addition: append to existing tables inside a GPKG without replacing them.  
If fields are missing in the target, add them automatically (schema alignment) so all attributes land correctly. Will be a separate tool to keep the “always new” exporter clear and safe.
- Small GUI plugin (toolbar button)  
- Examples & tests

---

## License

GPL-3.0 — see `LICENSE`.

---

## Trademarks

*Trimble* and *Trimble Access* are trademarks or registered trademarks of Trimble Inc.  
This project is not affiliated with Trimble.



