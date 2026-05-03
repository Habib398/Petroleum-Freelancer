"""modules/stations/routes.py

Módulo de estaciones de servicio — Blueprint nativo de Flask.
Migrado desde routes/stations.py a arquitectura modular.
"""
from __future__ import annotations
import uuid
import re
import json
import datetime

from flask import (
    Blueprint, request, jsonify,
    abort, current_app, g
)

from db import get_conn
from services.brand import get_brand

# Decoradores de autenticación compartidos (desacoplados de ctx)
from routes.auth import login_required, role_required

# ─── Blueprint ────────────────────────────────────────────────────────────────
bp = Blueprint("stations", __name__)


# ─── Helpers de coordenadas ───────────────────────────────────────────────────
def _parse_coord(val):
    """Acepta float/int decimal o cadena DMS como 25°40'11.97\"N. Retorna float o None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        pass
    m = re.match(
        r'^\s*(\d+(?:\.\d+)?)\s*[°d]\s*(\d+(?:\.\d+)?)\s*[\'′m]?\s*(\d+(?:\.\d+)?)\s*(?:["″s])?\s*([NSEW])\s*$',
        s, re.I
    )
    if not m:
        return None
    deg, mins, secs, hemi = m.groups()
    dec = float(deg) + float(mins) / 60.0 + float(secs) / 3600.0
    if hemi.upper() in ("S", "W"):
        dec *= -1.0
    return dec


def _coerce_lat_lng(data: dict):
    """Acepta lat/lng como número, decimal o DMS."""
    lat = _parse_coord(data.get("lat"))
    lng = _parse_coord(data.get("lng"))
    coord = (data.get("coord") or "").strip() if isinstance(data.get("coord"), str) else ""
    if (lat is None or lng is None) and coord:
        m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$', coord)
        if m:
            lat = float(m.group(1))
            lng = float(m.group(2))
    return lat, lng


# ─── Rutas ────────────────────────────────────────────────────────────────────
@bp.get("/api/stations")
@login_required
def api_stations():
    ctx = current_app.extensions['ctx']
    me = ctx.get_me()
    conn = get_conn()
    cur = conn.cursor()
    if ctx.has_global_station_scope(me):
        cur.execute(
            "SELECT * FROM stations WHERE brand=? ORDER BY COALESCE(station_number, id) ASC, id ASC",
            (get_brand(),)
        )
    else:
        scope = sorted(int(x) for x in ctx.station_scope_ids(me))
        if scope:
            qmarks = ",".join(["?"] * len(scope))
            cur.execute(
                f"SELECT * FROM stations WHERE brand=? AND id IN ({qmarks}) ORDER BY COALESCE(station_number, id) ASC, id ASC",
                (get_brand(), *scope)
            )
        else:
            cur.execute("SELECT * FROM stations WHERE 1=0")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"stations": rows})


@bp.get("/api/map/stations")
@login_required
def api_map_stations():
    ctx = current_app.extensions['ctx']
    me = ctx.get_me()
    if me.get("role") not in {"admin", "contador", "auditor"}:
        return jsonify({"error": "forbidden"}), 403
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, brand, name, code, station_number, group_name, state, city, address, lat, lng, monthly_status, monthly_end "
        "FROM stations ORDER BY COALESCE(station_number, id) ASC, id ASC"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"stations": rows})


@bp.post("/api/stations")
@login_required
@role_required("admin")
def api_station_create():
    ctx = current_app.extensions['ctx']
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    code = (data.get("code") or "").strip()
    if not name or not code:
        return jsonify({"error": "missing_name_or_code"}), 400
    lat, lng = _coerce_lat_lng(data)
    has_coord_payload = any(k in data and str(data.get(k) or '').strip() for k in ("lat", "lng", "coord"))
    if has_coord_payload and (lat is None or lng is None):
        return jsonify({
            "error": "invalid_coordinates",
            "hint": "Usa decimal (25.123,-100.456) o DMS (25°40'11.97\"N 100°18'05.72\"W)."
        }), 400
    conn = get_conn()
    cur = conn.cursor()
    brand = (data.get("brand") or get_brand()).strip().lower()
    if brand not in ("consulting", "petroleum"):
        brand = get_brand()
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name, state, city, address, lat, lng, monthly_status, monthly_end) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (brand, name, code, data.get("station_number"), data.get("group_name"),
         data.get("state"), data.get("city"), data.get("address"), lat, lng, "active", data.get("monthly_end")),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    me = ctx.get_me()
    ctx.log_action(me, "create_station", "stations", str(sid))
    return jsonify({"ok": True, "id": sid})


@bp.put("/api/stations/<int:station_id>")
@login_required
@role_required("admin")
def api_station_update(station_id):
    ctx = current_app.extensions['ctx']
    data = request.get_json(silent=True) or {}
    if "lat" in data or "lng" in data or "coord" in data:
        lat, lng = _coerce_lat_lng(data)
        has_coord_payload = any(k in data and str(data.get(k) or '').strip() for k in ("lat", "lng", "coord"))
        if has_coord_payload and (lat is None or lng is None):
            return jsonify({"error": "invalid_coordinates"}), 400
        data["lat"] = lat
        data["lng"] = lng
    fields = ["brand", "station_number", "group_name", "name", "code", "state", "city",
              "address", "lat", "lng", "monthly_status", "monthly_end"]
    if "brand" in data:
        b = (data.get("brand") or "").strip().lower()
        if b not in ("consulting", "petroleum"):
            data.pop("brand", None)
        else:
            data["brand"] = b
    sets = []
    vals = []
    for f in fields:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if not sets:
        return jsonify({"error": "no_changes"}), 400
    vals.append(station_id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE stations SET {', '.join(sets)} WHERE id=?", tuple(vals))
    conn.commit()
    conn.close()
    me = ctx.get_me()
    ctx.log_action(me, "update_station", "stations", str(station_id), {"fields": list(data.keys())})
    return jsonify({"ok": True})


@bp.delete("/api/stations/<int:station_id>")
@login_required
@role_required("admin")
def api_station_delete(station_id: int):
    ctx = current_app.extensions['ctx']
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM stations WHERE id=?", (station_id,))
    conn.commit()
    conn.close()
    me = ctx.get_me()
    ctx.log_action(me, "delete_station", "stations", str(station_id))
    return jsonify({"ok": True})


@bp.get("/api/map/fuel")
@login_required
def api_map_fuel():
    """Proxy a Overpass API para gasolineras dentro de un bbox."""
    ctx = current_app.extensions['ctx']
    me = ctx.get_me()
    if me.get("role") not in {"admin", "contador", "auditor"}:
        return jsonify({"error": "forbidden"}), 403
    bbox = (request.args.get("bbox") or "").strip()
    try:
        south, west, north, east = [float(x) for x in bbox.split(",")]
    except Exception:
        return jsonify({"error": "bad_bbox"}), 400
    import urllib.request
    import json as _json
    import urllib.parse
    q = (
        f"[out:json][timeout:25];"
        f"(node[amenity=fuel]({south},{west},{north},{east});"
        f"way[amenity=fuel]({south},{west},{north},{east});"
        f"relation[amenity=fuel]({south},{west},{north},{east}););"
        f"out center;"
    )
    data = urllib.parse.urlencode({"data": q}).encode("utf-8")
    url = "https://overpass-api.de/api/interpreter"
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "COG-WorkLog/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
        obj = _json.loads(payload)
    except Exception:
        return jsonify({"error": "overpass_unavailable"}), 502
    items = []
    for el in obj.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("brand") or "Gasolinera"
        items.append({
            "id": f"osm:{el.get('type')}:{el.get('id')}",
            "name": name,
            "lat": lat,
            "lng": lon,
            "brand": tags.get("brand"),
            "operator": tags.get("operator"),
        })
    return jsonify({"fuel": items})


@bp.post("/api/stations/import-kml")
@login_required
@role_required("admin")
def api_stations_import_kml():
    """Importa estaciones desde un archivo KML (Google Earth)."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Falta archivo (file)"}), 400
        f = request.files["file"]
        filename = (getattr(f, "filename", "") or "").lower()
        if not filename.endswith(".kml"):
            return jsonify({"ok": False, "error": "El archivo debe ser .kml"}), 400
        raw = f.read()
        if not raw:
            return jsonify({"ok": False, "error": "Archivo vacío"}), 400
        if len(raw) > 8 * 1024 * 1024:
            return jsonify({"ok": False, "error": "KML demasiado grande (máx 8MB)"}), 413
        try:
            import xml.etree.ElementTree as ET
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            root_xml = ET.fromstring(raw)
        except Exception:
            return jsonify({"ok": False, "error": "No se pudo leer el KML"}), 400

        def _tag_endswith(el, suffix: str) -> bool:
            return (el.tag or "").lower().endswith(suffix.lower())

        brand = get_brand()

        def _row_code(row):
            if row is None:
                return None
            try:
                return row["code"]
            except Exception:
                try:
                    return row[0]
                except Exception:
                    return None

        def _next_code(cur):
            prefix = "C-KML" if brand == "consulting" else "P-KML"
            cur.execute(
                "SELECT code FROM stations WHERE code LIKE ? ORDER BY code DESC LIMIT 1",
                (prefix + "-%",)
            )
            row = cur.fetchone()
            n = 1
            code_val = _row_code(row)
            if code_val:
                mm = re.match(rf"^{prefix}-(\d+)$", str(code_val))
                if mm:
                    n = int(mm.group(1)) + 1
            for _ in range(10000):
                code = f"{prefix}-{n:03d}"
                cur.execute("SELECT 1 FROM stations WHERE code=? LIMIT 1", (code,))
                if not cur.fetchone():
                    return code
                n += 1
            return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"

        created = []
        skipped = 0
        conn = get_conn()
        cur = conn.cursor()
        for pm in root_xml.iter():
            if not _tag_endswith(pm, "Placemark"):
                continue
            name = "Estación"
            for ch in list(pm):
                if _tag_endswith(ch, "name") and (ch.text or "").strip():
                    name = (ch.text or "").strip()
                    break
            coords_text = None
            for el in pm.iter():
                if _tag_endswith(el, "coordinates") and (el.text or "").strip():
                    coords_text = (el.text or "").strip()
                    break
            if not coords_text:
                skipped += 1
                continue
            first = coords_text.replace("\n", " ").replace("\t", " ").strip().split()[0]
            parts = first.split(",")
            if len(parts) < 2:
                skipped += 1
                continue
            try:
                lng_kml = float(parts[0])
                lat_kml = float(parts[1])
            except Exception:
                skipped += 1
                continue
            code = _next_code(cur)
            cur.execute(
                "INSERT INTO stations (brand, name, code, state, city, address, lat, lng, monthly_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')",
                (brand, name, code, None, None, None, lat_kml, lng_kml),
            )
            created.append({"name": name, "code": code, "lat": lat_kml, "lng": lng_kml})
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "count": len(created), "skipped": skipped, "created": created})
    except Exception as e:
        try:
            current_app.logger.exception(
                "KML import failed (trace=%s): %s", getattr(g, "trace_id", None), e
            )
        except Exception:
            pass
        return jsonify({
            "ok": False,
            "error": "server_error",
            "trace_id": getattr(g, "trace_id", None)
        }), 500
