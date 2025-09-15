# coding: utf-8
"""
Layer → GeoPackage (Export, immer neu & einfach)
- Nur 2 Parameter: Quell-Layer, Ziel-GPKG
- Es wird IMMER in eine neue Datei geschrieben:
  foo.gpkg → foo__1.gpkg → foo__2.gpkg … (keine Überschreiben-Abfrage)
- Erster Layer: Datei neu anlegen, weitere Layer: in dieselbe Datei schreiben
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
)
import os, re

class Layers2GPKG(QgsProcessingAlgorithm):
    P_LAYERS = "layers"
    P_GPKG   = "gpkg_path"

    def name(self): return "layers_to_gpkg_new_simple"
    def displayName(self): return "Layer → GeoPackage (Export, immer neu)"
    def group(self): return "Import LandXml"
    def groupId(self): return "import_landxml"

    def shortHelpString(self):
        return ("Exportiert ausgewählte Layer in ein GeoPackage.\n"
                "• Es wird immer eine NEUE Datei erzeugt (foo.gpkg → foo__1.gpkg → …), "
                "nie überschrieben.\n"
                "• Geometriespalte heißt 'geom', Spatial Index wird angelegt.")

    # -------- Parameter --------
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.P_LAYERS,
            "Quell-Layer auswählen",
            layerType=QgsProcessing.TypeVectorAnyGeometry
        ))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.P_GPKG, "GeoPackage-Zieldatei", fileFilter="GeoPackage (*.gpkg)"
        ))

    # -------- Helpers --------
    @staticmethod
    def _safe_table_name(vl: QgsVectorLayer) -> str:
        name = re.sub(r"[^\w\-]+", "_", vl.name().strip(), flags=re.UNICODE)
        return (name or "layer").strip("_")[:63]

    @staticmethod
    def _unique_gpkg_path(path: str) -> str:
        """foo.gpkg → foo.gpkg (frei) / foo__1.gpkg / foo__2.gpkg …"""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        if not ext:
            ext = ".gpkg"
        i = 1
        while True:
            cand = f"{base}__{i}{ext}"
            if not os.path.exists(cand):
                return cand
            i += 1

    def _write_table(self, gpkg_path: str, table_name: str,
                     src_layer: QgsVectorLayer, first_in_file: bool):
        """Schreibt eine Tabelle in gpkg_path (erste Tabelle legt die Datei an)."""
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName   = "GPKG"
        opts.layerName    = table_name
        opts.fileEncoding = "UTF-8"
        opts.layerOptions = ["GEOMETRY_NAME=geom", "SPATIAL_INDEX=YES"]

        # wichtig:
        # - für die ALLERERSTE Tabelle: Datei neu anlegen (CreateOrOverwriteFile)
        # - danach: nur noch Ebene anlegen/überschreiben (CreateOrOverwriteLayer)
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteFile
            if first_in_file else
            QgsVectorFileWriter.CreateOrOverwriteLayer
        )

        ct_ctx = QgsCoordinateTransformContext()
        ret = QgsVectorFileWriter.writeAsVectorFormatV3(src_layer, gpkg_path, ct_ctx, opts)

        # Fehlerbehandlung (API kann Tuple liefern)
        if isinstance(ret, tuple):
            code = ret[0]
            msg  = ret[1] if len(ret) > 1 else ""
        else:
            code = ret
            msg  = ""
        if code != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(
                f"Schreiben nach GPKG fehlgeschlagen ({table_name}): {msg}"
            )

        # Komfort: geschriebene Tabelle direkt ins Projekt laden
        uri = f"{gpkg_path}|layername={table_name}"
        from qgis.core import QgsVectorLayer
        lyr = QgsVectorLayer(uri, table_name, "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)

    # -------- main --------
    def processAlgorithm(self, parameters, context, feedback):
        layers    = self.parameterAsLayerList(parameters, self.P_LAYERS, context)
        gpkg_path = self.parameterAsFileOutput(parameters, self.P_GPKG, context)

        if not layers:
            raise QgsProcessingException("Keine Layer ausgewählt.")
        if not gpkg_path:
            raise QgsProcessingException("Kein Zielpfad angegeben.")

        # Ordner anlegen (falls nötig)
        folder = os.path.dirname(gpkg_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        # Immer neue Datei wählen
        gpkg_path = self._unique_gpkg_path(gpkg_path)
        feedback.pushInfo(f"Zieldatei: {gpkg_path}")

        first = True
        total = len(layers)
        for i, vl in enumerate(layers, 1):
            if feedback.isCanceled():
                break
            if not isinstance(vl, QgsVectorLayer) or not vl.isValid():
                feedback.pushWarning(f"Übersprungen (ungültig): {getattr(vl, 'name', lambda: '?')()}")
                continue

            table_name = self._safe_table_name(vl)
            feedback.pushInfo(f"[Write] {vl.name()} → {table_name}")
            self._write_table(gpkg_path, table_name, vl, first_in_file=first)
            first = False
            feedback.setProgress(int(i * 100.0 / total))

        return {"GPKG": gpkg_path}

    def createInstance(self):
        return Layers2GPKG()

def classFactory():
    return Layers2GPKG()
