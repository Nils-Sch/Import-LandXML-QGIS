# coding: utf-8
"""
QGIS Processing Algorithm: LandXML Import
- Punkte je Code (mit code-spezifischen Properties)
- Punkttabelle *mit Geometrie* (Id, Rechtswert, Hochwert, Hoehe, Code [voll])
- Linien (PlanFeature / Breakline / Alignment)
- CRS-Handling (epsgCode aus LandXML, Rückfragen bei Abweichung/Fehlen)
- Optional: DGM (Surfaces): Punkte, Faces (PolygonZ), Breaklines, Boundaries
- Ausgabe: NUR Temporärlayer (kein GeoPackage)
"""

from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFile, QgsProcessingParameterCrs,
    QgsProcessingParameterBoolean,
    QgsProcessingException, QgsProject,
    QgsVectorLayer, QgsFields, QgsField, QgsFeature, QgsGeometry,
    QgsPoint, QgsPointXY, QgsWkbTypes, QgsCoordinateTransformContext
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt import QtWidgets
import os, xml.etree.ElementTree as ET
from collections import defaultdict


class LandXMLImportAlg(QgsProcessingAlgorithm):
    # Parameter keys
    P_INPUT = "landxml_file"
    P_TARGET_CRS = "target_crs"
    P_SWAP_XY = "swap_xy"
    P_USE_LX_CRS = "use_landxml_crs"
    P_ASK_DIFF = "ask_if_crs_differs"
    P_ASK_MISSING = "ask_if_crs_missing"
    P_IMPORT_SURF = "import_surfaces"

    # ---- metadata ----
    def name(self):
        return "landxml_import"

    def displayName(self):
        return "LandXML Import"

    def group(self):
        return "Import LandXml"

    def groupId(self):
        return "import_landxml"

    def shortHelpString(self):
        return (
            "Importiert LandXML: Punkte je Code, Punkttabelle (mit Geometrie) "
            "und Linien (PlanFeature/Breakline/Alignment).\n"
            "CRS: LandXML epsgCode (optional) mit Rückfragen bei Abweichung/Fehlen.\n"
            "Optional: DGM (Surfaces) als Punkte, Dreiecks-Faces (PolygonZ) und Breaklines.\n"
            "Ausgabe nur als Temporärlayer (kein GeoPackage)."
        )

    # ---- parameters ----
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.P_INPUT, "LandXML-Datei", extension="xml"
        ))
        self.addParameter(QgsProcessingParameterCrs(
            self.P_TARGET_CRS, "Ziel-CRS (Fallback)", defaultValue="EPSG:25832"
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.P_SWAP_XY, "X/Y tauschen (wenn XML N,E liefert)", defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.P_USE_LX_CRS, "LandXML-CRS (epsgCode) verwenden, wenn vorhanden", defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.P_ASK_DIFF, "Nachfragen, wenn LandXML-CRS ≠ Projekt-CRS", defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.P_ASK_MISSING, "Nachfragen, wenn LandXML-CRS fehlt", defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.P_IMPORT_SURF, "DGM (Surfaces) importieren", defaultValue=True
        ))

    # ---- helpers ----
    @staticmethod
    def _floats(txt):
        if not txt:
            return []
        out = []
        for t in txt.strip().split():
            try:
                out.append(float(t))
            except:
                pass
        return out

    @staticmethod
    def _split_code(code_text):
        if not code_text:
            return "", ""
        s = code_text.strip()
        i = s.find(" ")
        return (s if i == -1 else s[:i], "" if i == -1 else s[i+1:].strip())

    @staticmethod
    def _safe_field(lbl, prefix="feat_"):
        return f"{prefix}{lbl}".replace(" ", "_").replace("-", "_").replace("/", "_")

    @staticmethod
    def _detect_landxml_epsg(root):
        """
        Sucht <CoordinateSystem epsgCode="...">. Gibt (epsg:int|None, info:str).
        """
        cs = root.find('.//{*}CoordinateSystem')
        if cs is None:
            return None, "Kein <CoordinateSystem> in LandXML."
        epsg_txt = cs.get('epsgCode') or cs.get('epsg') or ""
        name = cs.get('name') or cs.get('desc') or cs.get('ocs') or ""
        info = f"CoordinateSystem: {name}" if name else "CoordinateSystem vorhanden."
        if epsg_txt:
            try:
                return int(epsg_txt), f"{info} | EPSG={epsg_txt}"
            except:
                return None, f"{info} | epsgCode nicht numerisch: '{epsg_txt}'"
        return None, f"{info} | kein epsgCode-Attribut."

    def _map_xy_fn(self, swap_xy):
        return (lambda x, y: (y, x)) if swap_xy else (lambda x, y: (x, y))

    def _parts_from_pntlist(self, elem, map_xy):
        out = []
        # 3D
        p3 = elem.find('.//{*}PntList3D')
        if p3 is not None and p3.text and p3.text.strip():
            vals = self._floats(p3.text)
            pts = []
            for i in range(0, len(vals), 3):
                try:
                    x_raw, y_raw, z = vals[i], vals[i+1], vals[i+2]
                except IndexError:
                    break
                x, y = map_xy(x_raw, y_raw)
                pts.append((x, y, z))
            if len(pts) >= 2:
                out.append(pts)
        # 2D
        p2 = elem.find('.//{*}PntList2D')
        if p2 is not None and p2.text and p2.text.strip():
            vals = self._floats(p2.text)
            pts = []
            for i in range(0, len(vals), 2):
                try:
                    x_raw, y_raw = vals[i], vals[i+1]
                except IndexError:
                    break
                x, y = map_xy(x_raw, y_raw)
                pts.append((x, y, None))
            if len(pts) >= 2:
                out.append(pts)
        return out

    def _parse_coord(self, elem, map_xy, pt_coords):
        """<Start>/<End>: Koordinaten ODER Punkt-ID."""
        if elem is None or not (elem.text and elem.text.strip()):
            return None
        vals = self._floats(elem.text)
        if len(vals) >= 2:
            x_raw, y_raw = vals[0], vals[1]
            x, y = map_xy(x_raw, y_raw)
            z = vals[2] if len(vals) > 2 else None
            return (x, y, z)
        tok = elem.text.strip().split()[0]
        return pt_coords.get(tok)

    def _parts_from_coordgeom(self, container, map_xy, pt_coords):
        parts = []
        for ln in container.findall('.//{*}CoordGeom/{*}Line'):
            s = self._parse_coord(ln.find('./{*}Start'), map_xy, pt_coords)
            e = self._parse_coord(ln.find('./{*}End'), map_xy, pt_coords)
            if s and e:
                parts.append([s, e])
        return parts

    @staticmethod
    def _wkt_from_parts(parts):
        has_z = any(p[2] is not None for part in parts for p in part)
        if has_z:
            inner = ", ".join(["(" + ", ".join([f"{x} {y} {z}" for (x, y, z) in part]) + ")" for part in parts])
            return f"MULTILINESTRING Z({inner})", True
        else:
            inner = ", ".join(["(" + ", ".join([f"{x} {y}" for (x, y, _) in part]) + ")" for part in parts])
            return f"MULTILINESTRING({inner})", False

    # ---- einziges Ausgabe-Helferlein (nur temporär) ----
    def _add_or_write(self, layer):
        QgsProject.instance().addMapLayer(layer)

    # ---------- SURFACES (DGM) ----------
    def _import_surfaces(self, root, crs_uri, map_xy, feedback=None):
        """
        Erzeugt optional Surfaces:
          - Pnts (PointZ)
          - Faces (PolygonZ Dreiecke)
          - Breaklines (MultiLineString(Z))
          - Boundaries (outer/inner) als Kontrolle
        """
        def _emit(layer):
            self._add_or_write(layer)

        for surf in root.findall('.//{*}Surfaces/{*}Surface'):
            sname = surf.get('name') or surf.get('desc') or "Surface"

            # ===== Boundaries -> Maske (2D) =====
            boundary_outer_2d = None
            boundary_inners_2d = []

            def _poly2d_from_parts(parts):
                ring = parts[:]
                if len(ring) >= 3:
                    if ring[0] != ring[-1]:
                        ring = ring + [ring[0]]
                    wkt2d = "POLYGON((" + ", ".join([f"{x} {y}" for (x, y, _) in ring]) + "))"
                    return QgsGeometry.fromWkt(wkt2d)
                return None

            bnd_outer = surf.find('.//{*}SourceData/{*}Boundaries/{*}Boundary[@bndType="outer"]')
            if bnd_outer is not None:
                parts = self._parts_from_pntlist(bnd_outer, map_xy)
                if parts:
                    boundary_outer_2d = _poly2d_from_parts(parts[0])

            for bnd_in in surf.findall('.//{*}SourceData/{*}Boundaries/{*}Boundary[@bndType="inner"]'):
                parts = self._parts_from_pntlist(bnd_in, map_xy)
                if parts:
                    g = _poly2d_from_parts(parts[0])
                    if g:
                        boundary_inners_2d.append(g)

            mask2d = boundary_outer_2d
            if mask2d:
                for hole in boundary_inners_2d:
                    mask2d = mask2d.difference(hole)
                mask2d = mask2d.makeValid().buffer(0, 1)

            # Boundaries optional ausgeben (Kontrolle)
            if boundary_outer_2d:
                vlBnd = QgsVectorLayer(QgsWkbTypes.displayString(QgsWkbTypes.Polygon) + f"?crs={crs_uri}",
                                       f"{sname}_Boundary", "memory")
                pr = vlBnd.dataProvider()
                pr.addAttributes([QgsField("type", QVariant.String)])
                vlBnd.updateFields()
                f = QgsFeature(vlBnd.fields()); f["type"] = "outer"; f.setGeometry(boundary_outer_2d); pr.addFeatures([f])
                for i, g_h in enumerate(boundary_inners_2d, start=1):
                    f = QgsFeature(vlBnd.fields()); f["type"] = f"inner_{i}"; f.setGeometry(g_h); pr.addFeatures([f])
                _emit(vlBnd)

            # ===== Definition: Pnts =====
            pts_map = {}  # id -> (x,y,z)
            Pnts = surf.find('.//{*}Definition/{*}Pnts')
            if Pnts is not None:
                P_children = Pnts.findall('./{*}P')
                if P_children:
                    for p in P_children:
                        pid = p.get('id') or p.get('name')
                        vals = self._floats(p.text or "")
                        if not pid or len(vals) < 2:
                            continue
                        x_raw, y_raw = vals[0], vals[1]
                        z = vals[2] if len(vals) > 2 else None
                        x, y = map_xy(x_raw, y_raw)
                        pts_map[str(pid)] = (x, y, z)
                elif Pnts.text and Pnts.text.strip():
                    for ln in Pnts.text.strip().splitlines():
                        toks = ln.strip().split()
                        if len(toks) >= 4:
                            pid = toks[0]
                            try:
                                x_raw = float(toks[1]); y_raw = float(toks[2]); z = float(toks[3])
                            except ValueError:
                                continue
                            x, y = map_xy(x_raw, y_raw)
                            pts_map[str(pid)] = (x, y, z)

            if pts_map:
                wkb = QgsWkbTypes.PointZ if any(v[2] is not None for v in pts_map.values()) else QgsWkbTypes.Point
                uri = QgsWkbTypes.displayString(wkb) + f"?crs={crs_uri}"
                vlP = QgsVectorLayer(uri, f"{sname}_Pnts", "memory")
                prP = vlP.dataProvider()
                prP.addAttributes([QgsField("pid", QVariant.String), QgsField("z", QVariant.Double)])
                vlP.updateFields()
                feats = []
                for pid, (x, y, z) in pts_map.items():
                    f = QgsFeature(vlP.fields()); f["pid"] = pid; f["z"] = z
                    if wkb == QgsWkbTypes.PointZ and z is not None:
                        f.setGeometry(QgsGeometry.fromPoint(QgsPoint(x, y, z)))
                    else:
                        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    feats.append(f)
                if feats:
                    prP.addFeatures(feats); _emit(vlP)

            # ===== Definition: Faces (Dreiecke) =====
            Faces = surf.find('.//{*}Definition/{*}Faces')
            tri_geoms = []
            if Faces is not None:
                def plane_from_triangle(a, b, c):
                    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = a, b, c
                    det = (x1*(y2-y3) - y1*(x2-x3) + (x2*y3 - x3*y2))
                    if det == 0:
                        return (0.0, 0.0, z1)
                    A = ((z1*(y2 - y3) - y1*(z2 - z3) + (z2*y3 - z3*y2))) / det
                    B = ((x1*(z2 - z3) - z1*(x2 - x3) + (x2*z3 - x3*z2))) / det
                    C = ((x1*(y2*z3 - y3*z2) - y1*(x2*z3 - x3*z2) + z1*(x2*y3 - x3*y2))) / det
                    return (A, B, C)
                def z_at(A, B, C, x, y): return A*x + B*y + C

                def coords_from_ids(ids):
                    try:
                        return [pts_map[str(pid)] for pid in ids]
                    except KeyError:
                        return None

                for F in Faces.findall('./{*}F'):
                    ids = None
                    p1 = F.get('p1'); p2 = F.get('p2'); p3 = F.get('p3')
                    if p1 and p2 and p3:
                        ids = [p1, p2, p3]
                    elif F.text and F.text.strip():
                        toks = F.text.strip().split()
                        if len(toks) >= 3:
                            ids = toks[:3]
                    if not ids:
                        continue

                    tri = coords_from_ids(ids)
                    if not tri:
                        continue
                    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = tri
                    if None in (z1, z2, z3):
                        continue

                    ring2d = [(x1, y1), (x2, y2), (x3, y3), (x1, y1)]
                    A, B, C = plane_from_triangle((x1, y1, z1), (x2, y2, z2), (x3, y3, z3))
                    coordsZ = [(x, y, z_at(A, B, C, x, y)) for (x, y) in ring2d]
                    wkt = "POLYGON Z((" + ", ".join([f"{x} {y} {z}" for (x, y, z) in coordsZ]) + "))"
                    tri_geoms.append(QgsGeometry.fromWkt(wkt))

            if tri_geoms:
                if feedback:
                    feedback.pushInfo(f"[LandXML] TIN: {len(tri_geoms)} Dreieck(e) ohne Clipping ausgegeben.")
                uri = QgsWkbTypes.displayString(QgsWkbTypes.PolygonZ) + f"?crs={crs_uri}"
                vlF = QgsVectorLayer(uri, f"{sname}_Faces", "memory")
                prF = vlF.dataProvider()
                prF.addAttributes([QgsField("id", QVariant.Int)])
                vlF.updateFields()
                feats = []
                for i, g in enumerate(tri_geoms, start=1):
                    f = QgsFeature(vlF.fields()); f["id"] = i; f.setGeometry(g); feats.append(f)
                prF.addFeatures(feats); _emit(vlF)

            # ===== Breaklines =====
            Blks = surf.findall('.//{*}SourceData/{*}Breaklines/{*}Breakline')
            parts_list = []
            for bl in Blks or []:
                parts_list.extend(self._parts_from_pntlist(bl, map_xy))
            if parts_list:
                has_z = any(p[2] is not None for part in parts_list for p in part)
                wkb = QgsWkbTypes.MultiLineStringZ if has_z else QgsWkbTypes.MultiLineString
                uri = QgsWkbTypes.displayString(wkb) + f"?crs={crs_uri}"
                vlB = QgsVectorLayer(uri, f"{sname}_Breaklines", "memory")
                prB = vlB.dataProvider()
                prB.addAttributes([QgsField("name", QVariant.String)]); vlB.updateFields()
                feats = []
                for idx, part in enumerate(parts_list, start=1):
                    if has_z:
                        inner = "(" + ", ".join([f"{x} {y} {z}" for (x, y, z) in part]) + ")"
                        wkt = f"MULTILINESTRING Z({inner})"
                    else:
                        inner = "(" + ", ".join([f"{x} {y}" for (x, y, _) in part]) + ")"
                        wkt = f"MULTILINESTRING({inner})"
                    f = QgsFeature(vlB.fields()); f["name"] = f"BL_{idx}"
                    f.setGeometry(QgsGeometry.fromWkt(wkt)); feats.append(f)
                if feats:
                    prB.addFeatures(feats); _emit(vlB)

    # ---- main ----
    def processAlgorithm(self, parameters, context, feedback):
        # --- Parameter einlesen ---
        path = self.parameterAsFile(parameters, self.P_INPUT, context)
        target_crs = self.parameterAsCrs(parameters, self.P_TARGET_CRS, context)
        swap_xy = self.parameterAsBoolean(parameters, self.P_SWAP_XY, context)
        use_lx = self.parameterAsBoolean(parameters, self.P_USE_LX_CRS, context)
        ask_diff = self.parameterAsBoolean(parameters, self.P_ASK_DIFF, context)
        ask_missing = self.parameterAsBoolean(parameters, self.P_ASK_MISSING, context)
        import_surfaces = self.parameterAsBoolean(parameters, self.P_IMPORT_SURF, context)

        if not path or not os.path.isfile(path):
            raise QgsProcessingException("LandXML-Datei fehlt oder ist ungültig.")

        proj_epsg = QgsProject.instance().crs().postgisSrid() or None
        param_epsg = target_crs.postgisSrid() if hasattr(target_crs, "postgisSrid") else (proj_epsg or 25832)

        # --- XML parsen & EPSG prüfen ---
        tree = ET.parse(path); root = tree.getroot()
        lx_epsg, lx_info = self._detect_landxml_epsg(root)
        feedback.pushInfo(f"[LandXML] {lx_info}")

        # ---- CRS-Entscheidung inkl. Dialoge ----
        chosen_epsg = None
        if use_lx and lx_epsg:
            chosen_epsg = lx_epsg
            if ask_diff and proj_epsg and proj_epsg != lx_epsg:
                reply = QtWidgets.QMessageBox.question(
                    None,
                    "CRS abweichend",
                    (f"LandXML meldet EPSG:{lx_epsg}, Projekt hat EPSG:{proj_epsg}.\n\n"
                     f"Soll für die importierten Layer EPSG:{lx_epsg} verwendet werden?\n"
                     f"(Nein = Projekt-CRS verwenden)"),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes
                )
                chosen_epsg = lx_epsg if reply == QtWidgets.QMessageBox.Yes else proj_epsg or param_epsg

        if chosen_epsg is None:
            if ask_missing and not proj_epsg:
                epsg, ok = QtWidgets.QInputDialog.getInt(
                    None,
                    "CRS wählen",
                    "Bitte EPSG-Code eingeben.\n(Abbrechen = Parameter/Fallback verwenden)",
                    value=param_epsg, min=1000, max=999999
                )
                chosen_epsg = epsg if ok else param_epsg
            else:
                chosen_epsg = proj_epsg or param_epsg

        crs_uri = f"EPSG:{int(chosen_epsg)}"
        feedback.pushInfo(f"[LandXML] Verwende CRS {crs_uri} für neue Layer.")
        map_xy = self._map_xy_fn(swap_xy)
        ct_ctx = QgsCoordinateTransformContext()  # aktuell nicht benötigt, bleibt für Konsistenz

        # ---- Feature-Properties (CgPoints/Feature) nach code sammeln ----
        feature_props = {}
        for fe in root.findall('.//{*}CgPoints/{*}Feature'):
            code = fe.get('code')
            if not code:
                continue
            props = {}
            for pr in fe.findall('.//{*}Property'):
                lbl = (pr.get('label') or "").strip()
                val = pr.get('value')
                if lbl:
                    props[lbl] = val
            feature_props[code] = props

        # ---- Punkte lesen ----
        bucket_pts = defaultdict(list)  # gruppiert nach Code (bis erstes Leerzeichen)
        all_points = []                 # komplette Punktliste (für „Punkte_komplett“)
        pt_coords = {}                  # pid -> (x,y,z) (für Linien/CoordGeom)

        for p in root.findall('.//{*}CgPoints/{*}CgPoint'):
            pid = p.get('name') or p.get('id') or ""
            code_full = p.get('code') or ""
            code_base, code_suffix = self._split_code(code_full)
            desc = p.get('desc') or ""
            fref = p.get('featureRef') or ""

            vals = self._floats(p.text or "")
            if len(vals) < 2:
                continue
            x_raw, y_raw = vals[0], vals[1]
            x, y = map_xy(x_raw, y_raw)
            z = vals[2] if len(vals) > 2 else None

            pt_coords[pid] = (x, y, z)
            props = feature_props.get(fref, {})

            bucket_pts[code_base].append(dict(
                x=x, y=y, z=z, id=pid,
                code_full=code_full, code_suffix=code_suffix,
                desc=desc, props=props
            ))
            # Für die Gesamttabelle -> voller Code!
            all_points.append((pid, x, y, z, code_full))

        # ---- Punktlayer je Code (mit code-spezifischen Attributen) ----
        for code_base, recs in bucket_pts.items():
            if not recs:
                continue

            labels = set()
            has3d = any(r["z"] is not None for r in recs)
            for r in recs:
                labels.update(r["props"].keys())

            wkb = QgsWkbTypes.PointZ if has3d else QgsWkbTypes.Point
            uri = QgsWkbTypes.displayString(wkb) + f"?crs={crs_uri}"
            lname = f"CgPoints_{code_base}" if code_base else "CgPoints_(leer)"
            vl = QgsVectorLayer(uri, lname, "memory"); pr = vl.dataProvider()

            fields = QgsFields()
            fields.append(QgsField("Id", QVariant.String))
            fields.append(QgsField("code_full", QVariant.String))
            fields.append(QgsField("code_suffix", QVariant.String))
            fields.append(QgsField("desc", QVariant.String))
            fields.append(QgsField("z", QVariant.Double))
            for lbl in sorted(labels):
                fields.append(QgsField(self._safe_field(lbl), QVariant.String))
            pr.addAttributes(fields); vl.updateFields()

            feats = []
            for r in recs:
                f = QgsFeature(vl.fields())
                f["Id"] = r["id"]
                f["code_full"] = r["code_full"]
                f["code_suffix"] = r["code_suffix"]
                f["desc"] = r["desc"]
                f["z"] = r["z"]
                for lbl, val in r["props"].items():
                    key = self._safe_field(lbl)
                    if key in vl.fields().names():
                        f[key] = val
                if has3d and r["z"] is not None:
                    f.setGeometry(QgsGeometry.fromPoint(QgsPoint(r["x"], r["y"], r["z"])))
                else:
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r["x"], r["y"])))
                feats.append(f)
            pr.addFeatures(feats)
            self._add_or_write(vl)

        # ---- Punkttabelle mit Geometrie (komplett) ----
        # Inhalt: Id, Rechtswert, Hochwert, Hoehe, Code (vollständig)
        has_any_z = any((p[3] is not None) for p in all_points)
        wkb_all = QgsWkbTypes.PointZ if has_any_z else QgsWkbTypes.Point
        uri_all = QgsWkbTypes.displayString(wkb_all) + f"?crs={crs_uri}"
        vl_all = QgsVectorLayer(uri_all, "LandXML_Punkte_komplett", "memory")
        pr_all = vl_all.dataProvider()
        pr_all.addAttributes([
            QgsField("Id", QVariant.String),
            QgsField("Rechtswert", QVariant.Double),
            QgsField("Hochwert", QVariant.Double),
            QgsField("Hoehe", QVariant.Double),
            QgsField("Code", QVariant.String)
        ])
        vl_all.updateFields()

        feats_all = []
        for (pid, rw, hw, hz, code_full) in all_points:
            f = QgsFeature(vl_all.fields())
            f["Id"] = pid
            f["Rechtswert"] = rw
            f["Hochwert"] = hw
            f["Hoehe"] = hz
            f["Code"] = code_full
            if has_any_z and hz is not None:
                f.setGeometry(QgsGeometry.fromPoint(QgsPoint(rw, hw, hz)))
            else:
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(rw, hw)))
            feats_all.append(f)
        pr_all.addFeatures(feats_all)
        self._add_or_write(vl_all)

        # ---- Linien sammeln ----
        entries = []
        def parts_from_coordgeom(container): return self._parts_from_coordgeom(container, map_xy, pt_coords)
        def parts_from_pntlist(elem): return self._parts_from_pntlist(elem, map_xy)

        for pf in root.findall('.//{*}PlanFeatures/{*}PlanFeature'):
            name = pf.get('name') or pf.get('id') or ""
            desc = pf.get('desc') or ""
            parts = parts_from_pntlist(pf) + parts_from_coordgeom(pf)
            if parts:
                entries.append(("PlanFeature", name, desc, parts))

        for bl in root.findall('.//{*}Breaklines/{*}Breakline'):
            name = bl.get('name') or bl.get('id') or ""
            desc = bl.get('desc') or ""
            parts = parts_from_pntlist(bl)
            if parts:
                entries.append(("Breakline", name, desc, parts))

        for al in root.findall('.//{*}Alignments/{*}Alignment'):
            name = al.get('name') or al.get('id') or ""
            desc = al.get('desc') or ""
            parts = parts_from_coordgeom(al)
            if parts:
                entries.append(("Alignment", name, desc, parts))

        if entries:
            has_z_any = any(p[2] is not None for _, _, _, parts in entries for part in parts for p in part)
            wkb_ln = QgsWkbTypes.MultiLineStringZ if has_z_any else QgsWkbTypes.MultiLineString
            uri_ln = QgsWkbTypes.displayString(wkb_ln) + f"?crs={crs_uri}"
            vl_ln = QgsVectorLayer(uri_ln, "LandXML_Linien", "memory")
            pr_ln = vl_ln.dataProvider()

            fields_ln = QgsFields()
            fields_ln.append(QgsField("obj_type", QVariant.String))
            fields_ln.append(QgsField("obj_name", QVariant.String))
            fields_ln.append(QgsField("obj_desc", QVariant.String))
            pr_ln.addAttributes(fields_ln); vl_ln.updateFields()

            feats = []
            for (typ, name, desc, parts) in entries:
                wkt, _ = self._wkt_from_parts(parts)
                f = QgsFeature(vl_ln.fields())
                f["obj_type"] = typ
                f["obj_name"] = name
                f["obj_desc"] = desc
                f.setGeometry(QgsGeometry.fromWkt(wkt))
                feats.append(f)
            pr_ln.addFeatures(feats)
            self._add_or_write(vl_ln)

        # ---- Surfaces (DGM) optional ----
        if import_surfaces:
            self._import_surfaces(root, crs_uri, map_xy, feedback)

        return {}

    # Required by QGIS Processing
    def createInstance(self):
        return LandXMLImportAlg()


# QGIS entry point for Processing
def classFactory():
    return LandXMLImportAlg()
