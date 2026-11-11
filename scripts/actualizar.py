#!/usr/bin/env python3
"""Descarga incidencias y cámaras de la DGT (DATEX II) y avisos de AEMET (CAP),
los recorta por las zonas de zonas.json y escribe estado.json para la app.

Uso: python scripts/actualizar.py --salida out/ [--previo carpeta_con_cache.json]
Solo usa la biblioteca estándar. La clave de AEMET va en la variable AEMET_API_KEY.
"""
import argparse
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
URL_INCIDENCIAS = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
URL_CAMARAS = "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml"
URL_AEMET = "https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/{area}"
AREAS_AEMET = ["63", "67", "66", "71"]  # Asturias, Castilla y León, Cantabria y Galicia
# Recuadro amplio: Asturias y los tramos que entran en León, Cantabria y Galicia
BBOX_REGION = (42.45, -7.80, 43.80, -3.90)
UA = "mobilityastur-carretera/1.0 (+https://github.com/mobilityastur/carretera)"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
AHORA = datetime.now(timezone.utc)


# ---------- utilidades ----------

def descargar(url, cabeceras=None, intentos=3, espera=5):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(cabeceras or {})
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            ultimo = e
            print(f"  aviso: {url} intento {i + 1}: {e}", file=sys.stderr)
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                break  # límite de peticiones: reintentar solo lo empeora
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"no se pudo descargar {url}: {ultimo}")


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def hijos(el, nombre):
    return [c for c in el if local(c.tag) == nombre]


def primero(el, nombre):
    for c in el.iter():
        if local(c.tag) == nombre:
            return c
    return None


def texto(el, nombre):
    e = primero(el, nombre)
    return e.text.strip() if e is not None and e.text else None


def fecha(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso(d):
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if d else None


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def norm_via(s):
    return re.sub(r"\s+", "", (s or "").upper())


def en_bbox(lat, lon, b):
    return lat is not None and lon is not None and b[0] <= lat <= b[2] and b[1] <= lon <= b[3]


def humanizar(valor):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", valor or "")
    return s[:1].upper() + s[1:].lower()


# ---------- textos en castellano ----------

TEXTOS = {
    # causas y tipos generales
    "roadMaintenance": "Mantenimiento", "roadworks": "Obras", "maintenanceWork": "Trabajos de mantenimiento",
    "accident": "Accidente", "vehicleObstruction": "Vehículo averiado o detenido",
    "brokenDownVehicle": "Vehículo averiado", "obstruction": "Obstáculo en la vía",
    "objectOnTheRoad": "Objeto en la calzada", "animalPresence": "Animales en la vía",
    "infrastructureDamageObstruction": "Daños en la infraestructura", "damagedRoadSurface": "Firme en mal estado",
    "rockfalls": "Desprendimientos", "landslips": "Corrimiento de tierras", "fallenTrees": "Árbol caído",
    "flooding": "Inundación", "environmentalObstruction": "Obstáculo natural",
    "poorEnvironment": "Meteorología adversa", "poorEnvironmentConditions": "Meteorología adversa",
    "fog": "Niebla", "denseFog": "Niebla densa", "strongWinds": "Viento fuerte", "gales": "Temporal de viento",
    "heavySnowfall": "Nevada intensa", "snowfall": "Nevada", "heavyRain": "Lluvia intensa", "hail": "Granizo",
    "visibilityReduced": "Visibilidad reducida", "blizzard": "Ventisca",
    "snowOnTheRoad": "Nieve en la calzada", "ice": "Hielo", "blackIce": "Hielo", "icyPatches": "Placas de hielo",
    "slushOnRoad": "Nieve fundente", "freezingOfWetRoads": "Calzada helada", "wetIcyRoad": "Calzada helada",
    "snowDrifts": "Nieve acumulada", "packedSnow": "Nieve compactada", "slipperyRoad": "Calzada deslizante",
    "abnormalTraffic": "Tráfico", "stationaryTraffic": "Tráfico detenido", "queuingTraffic": "Retención",
    "slowTraffic": "Circulación lenta", "heavyTraffic": "Circulación densa",
    "congestion": "Retención", "roadSurfaceInPoorCondition": "Calzada en mal estado",
    "spillageOnTheRoad": "Vertido en la calzada", "vehicleStuck": "Vehículo atascado",
    "vehicleOnFire": "Vehículo ardiendo", "oilOnRoad": "Aceite en la calzada", "mudOnRoad": "Barro en la calzada",
    "looseChippings": "Gravilla suelta", "snowploughsInUse": "Quitanieves trabajando",
    "saltingInProgress": "Esparcido de sal", "gritting": "Esparcido de fundentes",
    # gestión de carriles
    "roadClosed": "Carretera cortada", "carriagewayClosures": "Calzada cortada",
    "laneClosures": "Carril cortado", "narrowLanes": "Carriles estrechados",
    "singleAlternateLineTraffic": "Paso alternativo", "lanesDeviated": "Desvío de carriles",
    "newRoadworksLayout": "Trazado provisional por obras", "contraflow": "Carril en sentido contrario",
    "doNotUseSpecifiedLanesOrCarriageways": "Carriles no utilizables",
    "useOfSpecifiedLanesOrCarriagewaysAllowed": "Uso de carriles específicos",
    "weightRestrictionInOperation": "Restricción de peso", "heightRestrictionInOperation": "Restricción de altura",
    "lengthRestrictionInOperation": "Restricción de longitud", "speedRestrictionInOperation": "Límite de velocidad",
    "overtakingProhibited": "Prohibido adelantar", "intermittentClosures": "Cortes intermitentes",
    "useSpecifiedLanes": "Uso de carriles específicos",
    # vialidad invernal
    "useSnowChains": "Cadenas obligatorias", "useSnowChainsOrTyres": "Cadenas o neumáticos de invierno",
    "winterTyresMandatory": "Neumáticos de invierno obligatorios", "snowChainsMandatory": "Cadenas obligatorias",
    "snowTyresMandatory": "Neumáticos de invierno obligatorios",
    "snowChainsOrTyresMandatory": "Cadenas o neumáticos de invierno",
    "doNotUseStudTyres": "Sin neumáticos de clavos",
    # carriles
    "rightLane": "carril derecho", "leftLane": "carril izquierdo", "middleLane": "carril central",
    "allLanesCompleteCarriageway": "toda la calzada", "rightHardShoulder": "arcén derecho",
    "leftHardShoulder": "arcén izquierdo", "hardShoulder": "arcén",
}

ROJOS = {"roadClosed", "carriagewayClosures", "useSnowChains", "snowChainsMandatory"}
MENORES = {"narrowLanes", "newRoadworksLayout", "lanesDeviated", "weightRestrictionInOperation",
           "heightRestrictionInOperation", "lengthRestrictionInOperation",
           "useOfSpecifiedLanesOrCarriagewaysAllowed", "speedRestrictionInOperation", "overtakingProhibited"}
CAMPOS_TIPO = ("causeType", "roadMaintenanceType", "accidentType", "abnormalTrafficType",
               "vehicleObstructionType", "obstructionType", "environmentalObstructionType",
               "infrastructureDamageType", "poorEnvironmentType", "weatherRelatedRoadConditionType",
               "nonWeatherRelatedRoadConditionType", "roadOrCarriagewayOrLaneManagementType",
               "winterEquipmentManagementType", "animalPresenceType", "constructionWorkType",
               "speedManagementType", "trafficControlType", "generalInstructionOrMessageToRoadUsersType",
               "driverInstruction", "reroutingManagementType", "roadsideAssistanceType")


def t(v):
    if v is None:
        return None
    if v in TEXTOS:
        return TEXTOS[v]
    return humanizar(v)


# ---------- incidencias DGT ----------

def puntos_de(loc):
    pts = []
    for el in loc.iter():
        pc = hijos(el, "pointCoordinates")
        if not pc:
            continue
        lat = num(texto(pc[0], "latitude"))
        lon = num(texto(pc[0], "longitude"))
        pts.append({
            "papel": local(el.tag),
            "lat": lat, "lon": lon,
            "km": num(texto(el, "kilometerPoint")),
            "provincia": texto(el, "province"),
            "municipio": texto(el, "municipality"),
        })
    return pts


def leer_incidencias(xml_bytes):
    raiz = ET.fromstring(xml_bytes)
    salida = []
    for sit in raiz.iter():
        if local(sit.tag) != "situation":
            continue
        sev_global = texto(sit, "overallSeverity")
        for rec in hijos(sit, "situationRecord"):
            loc = primero(rec, "locationReference")
            if loc is None:
                continue
            pts = puntos_de(loc)
            if not any(en_bbox(p["lat"], p["lon"], BBOX_REGION) for p in pts):
                continue
            tipos = []
            vehiculos = []
            comentarios = []
            for el in rec.iter():
                n = local(el.tag)
                val = (el.text or "").strip()
                if n in CAMPOS_TIPO and val:
                    if val == "_extended":
                        val = el.attrib.get("_extendedValue", val)
                    tipos.append(val)
                elif n == "vehicleType" and val:
                    vehiculos.append(val)
                elif n == "grossVehicleWeight" and val:
                    vehiculos.append(f">{val}t")
            # comentarios libres
            for gc in rec.iter():
                if local(gc.tag) in ("generalPublicComment", "nonGeneralPublicComment"):
                    for v in gc.iter():
                        if local(v.tag) == "value" and v.text and v.text.strip():
                            comentarios.append(v.text.strip())
            carril = None
            lu = primero(loc, "laneUsage")
            if lu is not None and lu.text:
                carril = lu.attrib.get("_extendedValue") if lu.text.strip() == "_extended" else lu.text.strip()
            kms = [p["km"] for p in pts if p["km"] is not None]
            inicio = fecha(texto(rec, "overallStartTime"))
            fin = fecha(texto(rec, "overallEndTime"))
            salida.append({
                "id": rec.attrib.get("id"),
                "situacion": sit.attrib.get("id"),
                "clase": local(rec.attrib.get(XSI_TYPE, "")).split(":")[-1],
                "via": texto(loc, "roadName"),
                "destino": texto(loc, "roadDestination"),
                "sentido": texto(loc, "tpegDirection"),
                "sentidoVia": texto(loc, "tpegDirectionRoad"),
                "puntos": pts,
                "kmIni": min(kms) if kms else None,
                "kmFin": max(kms) if kms else None,
                "tipos": list(dict.fromkeys(tipos)),
                "vehiculos": list(dict.fromkeys(vehiculos)),
                "carril": carril,
                "gravedad": texto(rec, "severity") or sev_global,
                "estadoValidez": texto(rec, "validityStatus"),
                "inicio": iso(inicio),
                "fin": iso(fin),
                "creada": iso(fecha(texto(rec, "situationRecordCreationTime"))),
                "comentarios": list(dict.fromkeys(comentarios)),
            })
    return salida


def solo_pesados(vehiculos):
    if not vehiculos:
        return False
    ligeros = {"anyVehicle", "car", "passengerCar", "carOrLightVehicle"}
    return not any(v in ligeros for v in vehiculos)


def clasificar(inc):
    """Devuelve (nivel 0-2, título, detalle) de una incidencia."""
    tipos = inc["tipos"]
    principal = next((x for x in tipos if x not in ("roadMaintenance", "poorEnvironment",
                                                      "infrastructureDamageObstruction",
                                                      "environmentalObstruction", "abnormalTraffic",
                                                      "obstruction")), tipos[0] if tipos else None)
    gestion = next((x for x in tipos if x in TEXTOS and x in (
        "roadClosed", "carriagewayClosures", "laneClosures", "narrowLanes", "singleAlternateLineTraffic",
        "lanesDeviated", "newRoadworksLayout", "contraflow", "doNotUseSpecifiedLanesOrCarriageways",
        "useOfSpecifiedLanesOrCarriagewaysAllowed", "weightRestrictionInOperation",
        "intermittentClosures")), None)
    invierno = next((x for x in tipos if x in ("useSnowChains", "useSnowChainsOrTyres", "winterTyresMandatory",
                                                "snowChainsMandatory", "snowTyresMandatory",
                                                "snowChainsOrTyresMandatory")), None)
    pesados = solo_pesados(inc["vehiculos"])
    carril_menor = inc["carril"] in ("rightHardShoulder", "leftHardShoulder", "hardShoulder")

    if invierno:
        titulo = t(invierno) + (" para camiones" if pesados else "")
        nivel = 1 if pesados or invierno not in ROJOS else 2
    elif gestion in ("roadClosed", "carriagewayClosures") and not pesados:
        titulo, nivel = t(gestion), 2
    elif gestion:
        causa = next((x for x in tipos if x in ("roadworks", "accident", "rockfalls", "landslips", "flooding",
                                                  "damagedRoadSurface", "fallenTrees")), None)
        texto_gestion = t(gestion)
        if gestion == "laneClosures" and carril_menor:
            texto_gestion = "Arcén cortado"
        titulo = f"{t(causa)} · {texto_gestion.lower()}" if causa else texto_gestion
        if gestion in ("roadClosed", "carriagewayClosures"):
            titulo += " (vehículos pesados)"
        nivel = 0 if (gestion in MENORES or carril_menor or pesados) else 1
    else:
        titulo = t(principal) or "Incidencia"
        nivel = 1
    if inc["gravedad"] in ("highest", "high") and nivel == 1 and not pesados:
        nivel = 2 if gestion in ROJOS else 1

    partes = []
    sitio = lugar(inc)
    if inc["kmIni"] is not None:
        a, b = inc["kmIni"], inc["kmFin"]
        partes.append(f"km {a:g}" if a == b else f"km {a:g} a {b:g}")
    if sitio:
        partes.append(sitio)
    if inc["sentidoVia"] == "both":
        partes.append("ambos sentidos")
    elif inc["destino"]:
        partes.append(f"sentido {inc['destino'].title()}")
    if inc["carril"] and inc["carril"] != "allLanesCompleteCarriageway":
        partes.append(t(inc["carril"]))
    return nivel, titulo, " · ".join(p for p in partes if p)


# ---------- cámaras DGT ----------

def leer_camaras(xml_bytes):
    raiz = ET.fromstring(xml_bytes)
    salida = []
    for dev in raiz.iter():
        if local(dev.tag) != "device":
            continue
        if (texto(dev, "typeOfDevice") or "").lower() != "camera":
            continue
        lat = num(texto(dev, "latitude"))
        lon = num(texto(dev, "longitude"))
        if not en_bbox(lat, lon, BBOX_REGION):
            continue
        salida.append({
            "id": dev.attrib.get("id"),
            "via": texto(dev, "roadName"),
            "destino": texto(dev, "roadDestination"),
            "km": num(texto(dev, "kilometerPoint")),
            "provincia": texto(dev, "province"),
            "lat": lat, "lon": lon,
            "url": texto(dev, "deviceUrl"),
            "actualizada": texto(dev, "lastUpdateOfDeviceInformation"),
        })
    return salida


def elegir(lista, maximo=8, clave=None):
    """Reparte 'maximo' elementos a lo largo del tramo. Con 'clave' (posición a lo largo
    del tramo) los reparte por distancia, para que no se amontonen donde hay muchas."""
    if maximo <= 0:
        return []
    if len(lista) <= maximo:
        return list(lista)
    if maximo == 1:
        return [lista[len(lista) // 2]]
    if clave is None:
        paso = (len(lista) - 1) / (maximo - 1)
        return [lista[round(i * paso)] for i in range(maximo)]
    pos = [clave(x) for x in lista]
    lo, hi = min(pos), max(pos)
    libres = list(range(len(lista)))
    elegidos = []
    for i in range(maximo):
        objetivo = lo + (hi - lo) * i / (maximo - 1)
        j = min(libres, key=lambda k: abs(pos[k] - objetivo))
        libres.remove(j)
        elegidos.append(lista[j])
    return elegidos


def orden_tramo(zona):
    modo = zona.get("orden", "lat-")
    if modo == "lon-":
        return lambda c: -(c["lon"] or 0)
    if modo == "lon+":
        return lambda c: c["lon"] or 0
    return lambda c: -(c["lat"] or 0)


PROVINCIA_LOCAL = {"ASTURIAS", "PRINCIPADO DE ASTURIAS"}


def lugar(inc):
    p = next((p for p in inc["puntos"] if p.get("municipio")), None) or next(
        (p for p in inc["puntos"] if p.get("provincia")), None)
    if not p:
        return None
    mun = (p.get("municipio") or "").strip()
    prov = (p.get("provincia") or "").strip()
    fuera = prov and prov.upper() not in PROVINCIA_LOCAL
    if mun and fuera and mun.upper() != prov.upper():
        return f"{mun} ({prov})"
    return mun or prov


# ---------- avisos AEMET ----------

NIVELES_AEMET = {"amarillo": 1, "naranja": 2, "rojo": 3}


def en_poligono(lat, lon, poli):
    dentro = False
    j = len(poli) - 1
    for i in range(len(poli)):
        yi, xi = poli[i]
        yj, xj = poli[j]
        if (xi > lon) != (xj > lon) and lat < (yj - yi) * (lon - xi) / ((xj - xi) or 1e-12) + yi:
            dentro = not dentro
        j = i
    return dentro


def leer_cap(xml_bytes):
    raiz = ET.fromstring(xml_bytes)
    if (texto(raiz, "msgType") or "").lower() == "cancel":
        return []
    salida = []
    for info in hijos(raiz, "info"):
        if not (texto(info, "language") or "").lower().startswith("es"):
            continue
        params = {}
        for p in hijos(info, "parameter"):
            params[texto(p, "valueName") or ""] = texto(p, "value") or ""
        nivel = (params.get("AEMET-Meteoalerta nivel") or "").lower()
        if nivel not in NIVELES_AEMET:
            continue
        expira = fecha(texto(info, "expires"))
        if expira and expira < AHORA:
            continue
        inicio = fecha(texto(info, "onset")) or fecha(texto(info, "effective"))
        fenomeno = params.get("AEMET-Meteoalerta fenomeno", "")
        fenomeno = fenomeno.split(";", 1)[-1] if fenomeno else ""
        if not fenomeno:
            m = re.search(r"[Aa]viso (?:especial )?de (.+?) de nivel", texto(info, "event") or "")
            fenomeno = m.group(1) if m else (texto(info, "event") or "")
        fenomeno = fenomeno[:1].upper() + fenomeno[1:]
        for area in hijos(info, "area"):
            poli = []
            for par in (texto(area, "polygon") or "").split():
                la, _, lo = par.partition(",")
                if num(la) is not None and num(lo) is not None:
                    poli.append((float(la), float(lo)))
            zona = None
            for g in hijos(area, "geocode"):
                if "zona" in (texto(g, "valueName") or "").lower():
                    zona = texto(g, "value")
            salida.append({
                "zona": zona,
                "zonaNombre": texto(area, "areaDesc"),
                "nivel": nivel,
                "nivelNum": NIVELES_AEMET[nivel],
                "fenomeno": fenomeno,
                "titulo": texto(info, "event"),
                "texto": texto(info, "description"),
                "probabilidad": params.get("AEMET-Meteoalerta probabilidad"),
                "inicio": iso(inicio),
                "fin": iso(expira),
                "ahora": bool(inicio is None or inicio <= AHORA),
                "poligono": poli,
            })
    return salida


def leer_avisos(clave):
    avisos = []
    for area in AREAS_AEMET:
        meta = json.loads(descargar(URL_AEMET.format(area=area), {"api_key": clave, "Accept": "application/json"})
                          .decode("latin-1"))
        if meta.get("estado") == 404 or not meta.get("datos"):
            print(f"  AEMET área {area}: sin avisos ({meta.get('descripcion')})")
            continue
        if meta.get("estado") not in (200, None):
            raise RuntimeError(f"AEMET área {area}: {meta}")
        datos = descargar(meta["datos"])
        try:
            with tarfile.open(fileobj=io.BytesIO(datos), mode="r:*") as tar:
                for m in tar.getmembers():
                    if m.isfile() and m.name.lower().endswith(".xml"):
                        avisos.extend(leer_cap(tar.extractfile(m).read()))
        except tarfile.ReadError:
            avisos.extend(leer_cap(datos))
    vistos, unicos = set(), []
    for a in sorted(avisos, key=lambda a: (a["zona"] or "", a["fenomeno"], a["nivelNum"], a["inicio"] or "")):
        k = (a["zona"], a["fenomeno"], a["inicio"], a["fin"])
        if k in vistos:
            continue
        vistos.add(k)
        prev = unicos[-1] if unicos else None
        # AEMET parte un mismo aviso en tramos seguidos: se unen en uno
        if (prev and (prev["zona"], prev["fenomeno"], prev["nivel"]) == (a["zona"], a["fenomeno"], a["nivel"])
                and prev["fin"] and a["inicio"]
                and fecha(a["inicio"]) <= fecha(prev["fin"]) + timedelta(minutes=2)):
            if (fecha(a["fin"]) or AHORA) > (fecha(prev["fin"]) or AHORA):
                prev["fin"] = a["fin"]
            prev["ahora"] = prev["ahora"] or a["ahora"]
            continue
        unicos.append(dict(a))
    unicos.sort(key=lambda a: (-a["nivelNum"], a["inicio"] or ""))
    return unicos


# ---------- composición ----------

def zona_de_incidencia(inc, zona):
    vias = {norm_via(v) for v in zona["carreteras"]}
    if norm_via(inc["via"]) not in vias:
        return False
    return any(en_bbox(p["lat"], p["lon"], zona["bbox"]) for p in inc["puntos"])


def resumen_zona(zona, incs, cams, avisos):
    activas, programadas = [], []
    limite = AHORA + timedelta(days=7)
    for inc in incs:
        if not zona_de_incidencia(inc, zona):
            continue
        ini, fin = fecha(inc["inicio"]), fecha(inc["fin"])
        if fin and fin < AHORA:
            continue
        nivel, titulo, detalle = clasificar(inc)
        p0 = next((p for p in inc["puntos"] if p["lat"] is not None), {})
        item = {"id": inc["id"], "nivel": nivel, "titulo": titulo, "detalle": detalle,
                "lat": p0.get("lat"), "lon": p0.get("lon"),
                "via": inc["via"], "inicio": inc["inicio"], "fin": inc["fin"],
                "comentario": " ".join(inc["comentarios"])[:280] or None}
        destino = programadas if ini and ini > AHORA else activas
        if destino is programadas and ini > limite:
            continue
        # la DGT suele dar una entrada por sentido: se juntan las que dicen lo mismo
        igual = next((x for x in destino if x["titulo"] == titulo and x["detalle"] == detalle), None)
        if igual is None:
            destino.append(item)
    activas.sort(key=lambda x: (-x["nivel"], x["inicio"] or ""), reverse=False)
    programadas.sort(key=lambda x: x["inicio"] or "")

    vias = {norm_via(v) for v in zona["carreteras"]}
    if zona.get("camaras"):
        ids = [str(i) for i in zona["camaras"]]
        sel = [c for c in cams if c["id"] in ids]
    else:
        clave = orden_tramo(zona)
        todas = sorted([c for c in cams if norm_via(c["via"]) in vias and en_bbox(c["lat"], c["lon"], zona["bbox"])],
                       key=clave)
        maximo = zona.get("maxCamaras", 8)
        foco = zona.get("foco")
        if foco:
            dentro = [c for c in todas if en_bbox(c["lat"], c["lon"], foco["bbox"])]
            fuera = [c for c in todas if c not in dentro]
            n_foco = min(foco.get("camaras", maximo // 2), len(dentro))
            sel = elegir(dentro, n_foco, clave) + elegir(fuera, maximo - n_foco, clave)
            if len(sel) < maximo:  # si un lado tiene pocas, se completa con el otro
                resto = [c for c in todas if c not in sel]
                sel += elegir(resto, maximo - len(sel), clave)
        else:
            sel = elegir(todas, maximo, clave)
        sel.sort(key=clave)
    camaras = [{"id": c["id"], "via": c["via"], "km": c["km"], "destino": c["destino"], "url": c["url"],
                "lat": c["lat"], "lon": c["lon"]}
               for c in sel if c["url"]]

    codigos = set(zona.get("aemet", []))
    av = [a for a in avisos if a["zona"] in codigos
          or any(en_poligono(la, lo, a["poligono"]) for la, lo in zona["puntos"])]
    av_salida = [{k: v for k, v in a.items() if k != "poligono"} for a in av]

    nivel = max([i["nivel"] for i in activas], default=0)
    graves = [i for i in activas if i["nivel"] == nivel and nivel > 0]
    if nivel == 2:
        estado, linea = "Cortes", graves[0]["titulo"]
        if any("adena" in i["titulo"] for i in graves):
            estado = "Cadenas"
        elif any("ortad" in i["titulo"] for i in graves):
            estado = "Cortada"
    elif nivel == 1:
        estado, linea = "Precaución", graves[0]["titulo"]
    elif activas:
        estado, linea = "Sin incidencias graves", activas[0]["titulo"]
    else:
        estado, linea = "Sin incidencias", "Circulación normal"
    return {
        "id": zona["id"], "nombre": zona["nombre"], "titulo": zona.get("titulo", zona["nombre"]),
        "tipo": zona["tipo"], "carreteras": zona["carreteras"], "tramo": zona.get("tramo"),
        "centro": zona["puntos"][0], "bbox": zona["bbox"],
        "nivel": nivel, "estado": estado, "resumen": linea,
        "incidencias": activas, "programadas": programadas,
        "camaras": camaras, "avisos": av_salida,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="out")
    ap.add_argument("--previo", default=None)
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    zonas = json.loads((RAIZ / "zonas.json").read_text(encoding="utf-8"))["zonas"]

    previo = {}
    ruta_previa = Path(args.previo) / "cache.json" if args.previo else None
    if ruta_previa and ruta_previa.exists():
        try:
            previo = json.loads(ruta_previa.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previo = {}
    cache_previa = previo.get("_cache", {})
    fuentes_previas = previo.get("fuentes", {})
    fuentes, cache = {}, {}

    def fuente(nombre, fn):
        try:
            datos = fn()
            fuentes[nombre] = {"ok": True, "hora": iso(AHORA), "n": len(datos)}
            cache[nombre] = datos
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {nombre}: {e}", file=sys.stderr)
            ant = fuentes_previas.get(nombre, {})
            fuentes[nombre] = {"ok": False, "hora": ant.get("hora"), "error": str(e)[:200], "n": ant.get("n", 0)}
            cache[nombre] = cache_previa.get(nombre, [])
        print(f"{nombre}: {fuentes[nombre]}")

    fuente("incidencias", lambda: leer_incidencias(descargar(URL_INCIDENCIAS, {"Accept": "application/xml"})))
    fuente("camaras", lambda: leer_camaras(descargar(URL_CAMARAS, {"Accept": "application/xml"})))
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    prev_av = fuentes_previas.get("avisos", {})
    hora_av = fecha(prev_av.get("hora"))
    if clave and prev_av.get("ok") and cache_previa.get("avisos") is not None and hora_av \
            and AHORA - hora_av < timedelta(minutes=25):
        # AEMET renueva los avisos pocas veces al día y la clave se comparte con la app de costa:
        # se piden como mucho cada 25-30 minutos para no pasar su límite de peticiones
        fuentes["avisos"] = prev_av
        cache["avisos"] = cache_previa["avisos"]
        print(f"avisos: reutilizados de {prev_av.get('hora')}")
    elif clave:
        fuente("avisos", lambda: leer_avisos(clave))
    else:
        fuentes["avisos"] = {"ok": False, "hora": None, "error": "Falta el secreto AEMET_API_KEY", "n": 0}
        cache["avisos"] = []

    res = [resumen_zona(z, cache["incidencias"], cache["camaras"], cache["avisos"]) for z in zonas]
    # avisos AEMET que afectan a alguna zona, para el banner
    vistos, banner = set(), []
    for z in res:
        for a in z["avisos"]:
            k = (a["zona"], a["fenomeno"], a["inicio"])
            if k not in vistos:
                vistos.add(k)
                banner.append({**a, "zonas": [x["nombre"] for x in res if any(
                    (b["zona"], b["fenomeno"], b["inicio"]) == k for b in x["avisos"])]})
    banner.sort(key=lambda a: (not a["ahora"], -a["nivelNum"], a["inicio"] or ""))

    estado = {
        "actualizado": iso(AHORA),
        "fuentes": fuentes,
        "avisos": banner,
        "zonas": res,
    }
    (salida / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, separators=(",", ":")),
                                        encoding="utf-8")
    # copia con datos en bruto para revisar y para reutilizar si una fuente falla
    (salida / "cache.json").write_text(json.dumps({"_cache": cache, "fuentes": fuentes}, ensure_ascii=False),
                                       encoding="utf-8")
    # resumen de depuración: todas las vías de la región con incidencias o cámaras
    vias = {}
    for inc in cache["incidencias"]:
        vias.setdefault(inc["via"], {"incidencias": 0, "camaras": 0, "tipos": set()})
        vias[inc["via"]]["incidencias"] += 1
        vias[inc["via"]]["tipos"].update(inc["tipos"])
    for c in cache["camaras"]:
        vias.setdefault(c["via"], {"incidencias": 0, "camaras": 0, "tipos": set()})
        vias[c["via"]]["camaras"] += 1
    (salida / "vias.json").write_text(json.dumps(
        {str(k): {**v, "tipos": sorted(v["tipos"])} for k, v in sorted(vias.items(), key=lambda x: str(x[0]))},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ok: {len(res)} zonas, {sum(len(z['incidencias']) for z in res)} incidencias, "
          f"{sum(len(z['camaras']) for z in res)} cámaras, {len(banner)} avisos")


if __name__ == "__main__":
    main()
