from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand
from services.storage import get_storage


def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/uploads/<path:relpath>")
    @login_required
    def download(relpath):
        me = ctx.get_me()
        # blocked stations cannot download anything
        if ctx.station_blocked(me) and me["role"] != "admin":
            return jsonify({"error":"station_blocked"}), 403

        # Special case: orgchart uploaded photos should only be visible inside the matching brand.
        if (relpath or '').replace('\\', '/').startswith('orgchart/'):
            active_brand = get_brand()
            parts = (relpath or '').replace('\\', '/').split('/')
            file_brand = parts[1].strip().lower() if len(parts) > 1 else ''
            if me.get('role') != 'admin' and (not file_brand or file_brand != active_brand):
                return jsonify({"error":"forbidden"}), 403

        # authorize by station ownership unless admin
        conn = get_conn(); cur = conn.cursor()
        # check various tables for ownership
        tables = [
            ("submissions","evidence_path"),
            ("pipas","ticket_path"),("pipas","factura_path"),("pipas","before_path"),("pipas","after_path"),
            ("payments","proof_path"),("payments","invoice_path"),
            ("maintenance","evidence_before"),("maintenance","evidence_after"),
            ("bitacoras","evidence_path"),
            ("station_profiles","fiel_cer_path"),("station_profiles","fiel_key_path"),
            # Docs library
            ("documents","file_path"),
            ("document_versions","file_path"),
            ("evidence_photos","file_path"),
        ]
        owner_station_id = None
        owner_doc_module = None
        owner_doc_section = None
        for table,col in tables:
            # documents: table may not have station_id/module/section historically; tolerate
            try:
                cur.execute(f"SELECT station_id, module, section FROM {table} WHERE {col}=? LIMIT 1", (relpath,))
            except Exception:
                try:
                    cur.execute(f"SELECT station_id, module FROM {table} WHERE {col}=? LIMIT 1", (relpath,))
                except Exception:
                    cur.execute(f"SELECT station_id FROM {table} WHERE {col}=? LIMIT 1", (relpath,))
            row = cur.fetchone()
            if row:
                try:
                    owner_station_id = row["station_id"]
                except Exception:
                    owner_station_id = row[0] if row else None
                try:
                    owner_doc_module = row["module"]
                except Exception:
                    owner_doc_module = None
                try:
                    owner_doc_section = row["section"]
                except Exception:
                    owner_doc_section = None
                break

        # Calibraciones tank docs are stored on cal_tanks
        if owner_station_id is None:
            try:
                cur.execute(
                    """
                    SELECT station_id, 'calibraciones' as module
                    FROM cal_tanks
                    WHERE pdf_path=? OR sonda_pdf_path=? OR temp_pdf_path=?
                    LIMIT 1
                    """,
                    (relpath, relpath, relpath),
                )
                r2 = cur.fetchone()
                if r2:
                    owner_station_id = r2["station_id"]
                    owner_doc_module = "calibraciones"
            except Exception:
                pass

        # Petroleum: simple norms and compliance files must respect station scope too
        if owner_station_id is None:
            try:
                cur.execute(
                    "SELECT fuel_type, 'petroleum_norms' as module FROM petroleum_norm_files WHERE stored_path=? LIMIT 1",
                    (relpath,),
                )
                r3 = cur.fetchone()
                if r3:
                    fuel_scope = (r3['fuel_type'] or '')
                    if isinstance(fuel_scope, str) and fuel_scope.startswith('station:'):
                        try:
                            owner_station_id = int(fuel_scope.split(':', 1)[1])
                        except Exception:
                            owner_station_id = None
                    owner_doc_module = 'petroleum_norms'
            except Exception:
                pass
        if owner_station_id is None:
            try:
                cur.execute(
                    "SELECT station_id, 'compliance' as module FROM compliance_files WHERE stored_path=? LIMIT 1",
                    (relpath,),
                )
                r4 = cur.fetchone()
                if r4:
                    owner_station_id = r4["station_id"]
                    owner_doc_module = "compliance"
            except Exception:
                pass
        conn.close()

        if me["role"] != "admin":
            if relpath.startswith("sasisopa_submissions/") or relpath.startswith("sgm_submissions/"):
                return jsonify({"error":"forbidden"}), 403
            # Calibraciones documents are admin-only for now
            if "/docs/calibraciones/" in (relpath or ""):
                return jsonify({"error":"forbidden"}), 403

            # Calibraciones tank docs are admin-only
            if owner_doc_module == "calibraciones":
                return jsonify({"error":"forbidden"}), 403

            # Petroleum norms/compliance allow delegated station scope.
            if owner_doc_module in {"petroleum_norms", "compliance"}:
                if owner_station_id is None or not ctx.can_access_station(me, int(owner_station_id)):
                    return jsonify({"error":"forbidden"}), 403
            # Shared-folder docs respect delegated station scope; other library docs stay local to the station.
            elif owner_doc_module is not None:
                if owner_doc_module == "general" and (owner_doc_section or "").strip().lower() in {"shared", "pending_docs"}:
                    if owner_station_id is None or not ctx.can_access_station(me, int(owner_station_id)):
                        return jsonify({"error":"forbidden"}), 403
                else:
                    my_station_id = int(me.get("station_id") or -1)
                    if owner_station_id is None or int(owner_station_id) != my_station_id:
                        return jsonify({"error":"forbidden"}), 403
            elif owner_station_id is not None and int(owner_station_id) != int(me.get("station_id") or -1):
                return jsonify({"error":"forbidden"}), 403
        # Inline viewing when requested and allowed.
        inline_q = (request.args.get("inline") or "").strip().lower() in {"1", "true", "yes"}
        as_attachment = True
        if inline_q:
            rp = (relpath or "").replace("\\", "/").lower()
            if rp.endswith(".pdf") or rp.endswith(".png") or rp.endswith(".jpg") or rp.endswith(".jpeg") or rp.endswith(".webp"):
                # If user passed checks above, allow inline
                as_attachment = False

        ctx.log_action(me, "download_file", "uploads", relpath, {"station_id": owner_station_id, "inline": (not as_attachment)})
        return get_storage().send(relpath, as_attachment=as_attachment)

    # ---------------- admin: users & stations ----------------

