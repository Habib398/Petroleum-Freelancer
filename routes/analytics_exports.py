from __future__ import annotations

import csv
import datetime
import io

from flask import jsonify, request, Response, current_app, abort
from openpyxl import Workbook

from db import get_conn
from services.brand import get_brand

ALLOWED_FUEL = ("magna","premium","diesel")


def _send_file_bytes(blob: bytes, filename: str, mimetype: str):
    resp = Response(blob, mimetype=mimetype)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    get_me = ctx.get_me
    require_station = ctx.require_station
    log_action = ctx.log_action

    def _coerce_date(s: str) -> str:
        try:
            datetime.date.fromisoformat(s)
            return s
        except Exception:
            return ""

    @app.get("/api/analytics/liters")
    @login_required
    def api_analytics_liters():
        me = get_me()
        q_station = (request.args.get("station_id") or "").strip()
        group = (request.args.get("group") or "day").strip()
        date_from = _coerce_date(request.args.get("from", "")) or (
            datetime.date.today().replace(day=1).isoformat()
        )
        date_to = _coerce_date(request.args.get("to", "")) or datetime.date.today().isoformat()

        if group not in ("day","month"):
            group = "day"

        if me["role"] == "admin":
            station_id = int(q_station) if q_station else None
        else:
            station_id = require_station(me)

        conn = get_conn(); cur = conn.cursor()
        params=[]
        brand = get_brand()
        where = "WHERE p.brand=? AND date(p.created_at) BETWEEN date(?) AND date(?)"
        params += [brand, date_from, date_to]
        if station_id:
            where += " AND p.station_id=?"
            params.append(station_id)

        if group == "day":
            cur.execute(
                f"""
                SELECT date(p.created_at) as bucket,
                       lower(p.fuel_type) as fuel,
                       sum(p.liters) as liters
                FROM pipas p
                {where}
                GROUP BY bucket, fuel
                ORDER BY bucket ASC
                """,
                params,
            )
        else:
            cur.execute(
                f"""
                SELECT substr(date(p.created_at),1,7) as bucket,
                       lower(p.fuel_type) as fuel,
                       sum(p.liters) as liters
                FROM pipas p
                {where}
                GROUP BY bucket, fuel
                ORDER BY bucket ASC
                """,
                params,
            )

        rows = cur.fetchall()
        conn.close()

        series = {}
        for r in rows:
            b = r["bucket"]
            f = (r["fuel"] or "").lower()
            if f not in ALLOWED_FUEL:
                continue
            series.setdefault(b, {ft:0 for ft in ALLOWED_FUEL})
            series[b][f] = float(r["liters"] or 0)

        out = [{"bucket": b, **vals} for b, vals in series.items()]
        log_action(me, "analytics_view", "analytics", "liters", {"from": date_from, "to": date_to, "group": group, "station_id": station_id})
        return jsonify({"items": out})

    @app.get("/api/export/pipas.csv")
    @login_required
    def export_pipas_csv():
        me = get_me()
        if me["role"] not in {"admin","auditor"}:
            abort(403)
        station_id = (request.args.get("station_id") or "").strip()

        conn=get_conn(); cur=conn.cursor()
        if station_id:
            cur.execute("SELECT * FROM pipas WHERE brand=? AND station_id=? ORDER BY created_at DESC", (get_brand(), int(station_id),))
        else:
            cur.execute("SELECT * FROM pipas WHERE brand=? ORDER BY created_at DESC", (get_brand(),))
        rows=cur.fetchall(); conn.close()

        buf=io.StringIO()
        w=csv.writer(buf)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
        blob=buf.getvalue().encode("utf-8")
        log_action(me, "export_csv", "pipas", station_id or "all")
        return _send_file_bytes(blob, "pipas.csv", "text/csv; charset=utf-8")

    @app.get("/api/export/pipas.xlsx")
    @login_required
    def export_pipas_xlsx():
        me = get_me()
        if me["role"] not in {"admin","auditor"}:
            abort(403)
        station_id = (request.args.get("station_id") or "").strip()

        conn=get_conn(); cur=conn.cursor()
        if station_id:
            cur.execute("SELECT * FROM pipas WHERE brand=? AND station_id=? ORDER BY created_at DESC", (get_brand(), int(station_id),))
        else:
            cur.execute("SELECT * FROM pipas WHERE brand=? ORDER BY created_at DESC", (get_brand(),))
        rows=cur.fetchall(); conn.close()

        wb=Workbook()
        ws=wb.active
        ws.title="pipas"
        if rows:
            ws.append(list(rows[0].keys()))
            for r in rows:
                ws.append(list(r))
        bio=io.BytesIO()
        wb.save(bio)
        blob=bio.getvalue()
        log_action(me, "export_xlsx", "pipas", station_id or "all")
        return _send_file_bytes(blob, "pipas.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/api/export/submissions.csv")
    @login_required
    def export_submissions_csv():
        me = get_me()
        if me["role"] not in {"admin","auditor"}:
            abort(403)
        station_id = (request.args.get("station_id") or "").strip()

        conn=get_conn(); cur=conn.cursor()
        if station_id:
            cur.execute("SELECT * FROM submissions WHERE brand=? AND station_id=? ORDER BY created_at DESC", (get_brand(), int(station_id),))
        else:
            cur.execute("SELECT * FROM submissions WHERE brand=? ORDER BY created_at DESC", (get_brand(),))
        rows=cur.fetchall(); conn.close()

        buf=io.StringIO()
        w=csv.writer(buf)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
        blob=buf.getvalue().encode("utf-8")
        log_action(me, "export_csv", "submissions", station_id or "all")
        return _send_file_bytes(blob, "submissions.csv", "text/csv; charset=utf-8")

    @app.get("/api/export/submissions.xlsx")
    @login_required
    def export_submissions_xlsx():
        me = get_me()
        if me["role"] not in {"admin","auditor"}:
            abort(403)
        station_id = (request.args.get("station_id") or "").strip()

        conn=get_conn(); cur=conn.cursor()
        if station_id:
            cur.execute("SELECT * FROM submissions WHERE brand=? AND station_id=? ORDER BY created_at DESC", (get_brand(), int(station_id),))
        else:
            cur.execute("SELECT * FROM submissions WHERE brand=? ORDER BY created_at DESC", (get_brand(),))
        rows=cur.fetchall(); conn.close()

        wb=Workbook(); ws=wb.active; ws.title="submissions"
        if rows:
            ws.append(list(rows[0].keys()))
            for r in rows:
                ws.append(list(r))
        bio=io.BytesIO(); wb.save(bio)
        blob=bio.getvalue()
        log_action(me, "export_xlsx", "submissions", station_id or "all")
        return _send_file_bytes(blob, "submissions.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
