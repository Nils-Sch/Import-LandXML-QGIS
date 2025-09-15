> **Deutsche Version.** [Rohansicht (ohne Übersetzung)](README.md?plain=1) · English: [README_en.md](README_en.md)

# Import-LandXML-QGIS
...

> English version: see [README_en.md](README_en.md)
# Import-LandXML-QGIS

QGIS-Processing-Skripte, um Messdaten – vor allem aus Trimble Access – schnell und robust in QGIS zu bringen: ohne DXF-Umwege und ohne Überschreiben.

> Warum? Die DXF-Writer in Trimble Access bzw. der Trimble ASCII File Generator sind für schnelle Übergaben oft umständlich. Dieses Repo setzt auf LandXML/CSV → QGIS und schreibt dann sauber als GeoPackage (GPKG).

---

## Tools im Paket

- **Layer → GeoPackage (neu & Datum)**  
  Exportiert ausgewählte Vektorlayer in ein neues GeoPackage.  
  Der Dateiname erhält einen Zeitstempel (`…__YYYY-mm-dd_HHMM.gpkg`).  
  Es wird nie überschrieben.

- **Layer → GeoPackage (neu)**  
  Wie oben, nur ohne Zeitstempel. Ebenfalls immer neue Datei.

- **LandXml2QGIS**  
  Helfer rund um LandXML (Punkte / Breaklines / Faces → Layer).  
  Hinweis: LandXML kann von QGIS/OGR leicht unterschiedlich interpretiert werden; diese Skripte liefern feste Layernamen und Z-Unterstützung.

Die Tools findest du in QGIS unter **Verarbeitung → Skripte → Import LandXml**.

---

## Voraussetzungen

- QGIS 3.40 (getestet)  
- Python 3.12 (in QGIS enthalten)  
- GDAL 3.11+

---

## Installation

1. **Skripte kopieren**  
   Lege die Dateien aus `scripts/` in diesen Ordner: %APPDATA%\QGIS\QGIS3\profiles<DEIN_PROFIL>\processing\scripts\
   (Ersetze `<DEIN_PROFIL>` durch deinen Profilnamen. Falls Ordner fehlen, einfach anlegen.)

2. **QGIS neu einlesen lassen**  
- Am einfachsten: QGIS neu starten.  
- Alternative ohne Neustart: **Plugins → Plugins verwalten… → „Verarbeitung/Processing“** kurz deaktivieren und wieder aktivieren.  
- Profi-Variante (Python-Konsole):
  ```python
  from qgis.core import QgsApplication
  prov = QgsApplication.processingRegistry().providerById('script')
  if prov:
      prov.refreshAlgorithms()
      print("Skript-Provider neu geladen.")
  ```

3. Die Tools erscheinen unter **Verarbeitung → Skripte → Import LandXml**.

---

## Typischer Workflow

1. **Koordinaten, Linien, Polygone, Breaklines oder Faces** exportieren  
(z. B. LandXML-Export aus Trimble Access oder einer anderen Quelle).
2. In QGIS laden (LandXML in Layer zerlegen; Punkte/Breaklines/Faces).
3. **Layer → GeoPackage (neu & Datum)** starten, Zieldatei wählen → **Ausführen**.  
- Ergebnis: `…__YYYY-mm-dd_HHMM.gpkg` (bei Kollision automatisch `…__1.gpkg`, `…__2.gpkg` …)  
- Geometriespalte = `geom`, Spatial Index aktiv

> Hinweis: CSV/WKT-Unterstützung (Punkte, Linien via WKT oder „Punkte zu Pfaden“) ist vorgesehen, wird aber später dokumentiert, sobald getestet.

---

## Design-Entscheidungen

- **Sicher & nachvollziehbar:** immer neues GPKG (optional mit Zeitstempel), keine „Überschreiben?“-Dialoge.  
- **Saubere Geometriespalte:** immer `geom`, plus Spatial Index.  
- **Z-Werte:** werden übernommen, wenn vorhanden.  
- **CRS:** keine automatische Umprojektion – beim Import korrekt setzen (häufig EPSG:25832).

---

## Troubleshooting

- **Layer unsichtbar / Warnsymbol:** Rechtsklick → *Auf Layer zoomen*. Projekt-CRS prüfen (OTF an, passendes EPSG). Einfaches Styling testen.  
- **GPKG wirkt leer:** Attributtabelle öffnen; wenn leer, Quelle prüfen (Filter? falsches CRS?).  
- **Windows-Crash beim Überschreiben:** vermeiden wir, weil wir immer neu schreiben.

---

## Roadmap

- **Separates Tool „Append (mit Schema-Abgleich)“**  
Geplanter Zusatz: Bestehende Tabellen in einem GPKG weiterbefüllen (anhängen), ohne sie zu ersetzen.  
Fehlen im Ziel Felder, werden sie automatisch ergänzt (Schema-Angleichung), damit alle Attribute sauber ankommen. Kommt als eigenes Tool, damit der „immer neu“-Export klar und sicher bleibt.
- Kleines GUI-Plugin (Toolbar-Button)  
- Beispiele & Tests

---

## Lizenz

GPL-3.0 – siehe `LICENSE`.

---

## Markenhinweis

*Trimble* und *Trimble Access* sind Marken bzw. eingetragene Marken der Trimble Inc.  
Dieses Projekt steht in keiner Verbindung zu Trimble.

