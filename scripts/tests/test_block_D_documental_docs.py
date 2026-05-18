"""Bloque D · Documental con PDF + coordenadas (SASISOPA / SGM)

Verifica el motor documental que comparten **SASISOPA** y **SGM**. La
fábrica está en ``modules/compliance/documental_docs.py``: registra un set
idéntico de rutas para cada ``module_key`` (``sasisopa`` y ``sgm``), todas
prefijadas con ``/admin/<modulo>/docs/...`` y ``/staff/<modulo>/docs/...``.

Las cuatro tablas comparten esquema (``doc_templates``,
``doc_requirements``, ``doc_submissions``, ``doc_records``) y se distinguen
por ``(brand, module)``. La columna ``module`` se agrega vía
``ensure_column`` con default ``'sasisopa'`` ([db.py:1197-1200](db.py#L1197)).

Áreas cubiertas:

* ``GET /api/<modulo>/docs/health`` retorna JSON con contadores.
* ``POST /admin/<modulo>/docs/templates/upload`` sube un PDF (válido,
  generado por pymupdf), crea fila en ``doc_templates`` y genera previews
  PNG por página vía pymupdf.
* ``POST /admin/<modulo>/docs/templates/<id>/fields`` guarda el esquema
  de campos (JSON con coordenadas, page, x, y, w, h, font_size, align…).
* ``POST /admin/<modulo>/docs/templates/<id>/publish`` marca
  ``is_published=1``.
* ``POST /admin/<modulo>/docs/templates/<id>/record`` (admin capture)
  renderiza el PDF con los valores de los campos y crea un ``doc_records``
  para la estación. Re-POST con la misma estación hace **upsert** (un
  registro vigente por estación, por ``UNIQUE(brand, module, station_id)``).
* ``GET /admin/<modulo>/docs/records/<id>/download`` descarga el PDF
  renderizado.
* ``GET /staff/<modulo>/docs/records`` lista records para staff filtrados
  por su scope de estación.
* ``GET /staff/<modulo>/docs/records/<id>/download`` staff puede bajar
  records de su estación, no de otras (403).
* **Aislamiento por module y brand**: sasisopa y sgm comparten tablas
  pero se filtran por ``module``. Templates de petroleum no se mezclan
  con consulting.
* **Single-submission policy**: ``capture_submit`` (legacy de staff) está
  cerrada por diseño (abort 403 con mensaje). ``unlock_requirement``
  abort 400 con "Desbloqueo deshabilitado".
* **Role gate**: staff no puede entrar a rutas ``/admin/...``.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    db_get,
    db_row_count,
    login,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


def days_from_today(n: int) -> str:
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def set_session_brand(env, brand: str) -> None:
    with env.client.session_transaction() as s:
        s["brand"] = brand


def make_minimal_pdf_bytes(n_pages: int = 1, title: str = "Plantilla Test") -> bytes:
    """Genera un PDF válido con pymupdf que el endpoint pueda re-abrir.

    No basta con un PDF "magic-header only": el endpoint llama
    ``fitz.open(src)`` y luego ``doc.load_page(i).get_pixmap(...)`` para
    generar previews PNG. Necesitamos páginas reales con contenido.
    """
    try:
        import pymupdf as fitz
    except Exception:
        import fitz
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((100, 100 + i * 30), f"{title} · página {i + 1}",
                          fontsize=12, fontname="helv")
    buf = io.BytesIO(doc.write())
    doc.close()
    return buf.getvalue()


SAMPLE_SCHEMA = [
    {
        "key": "fecha", "label": "Fecha", "page": 0,
        "x": 380, "y": 130, "w": 140, "h": 18,
        "font_size": 10, "max_len": 40, "align": "left",
        "type": "date", "placeholder": "2026-01-15",
        "staff_editable": True,
    },
    {
        "key": "responsable", "label": "Responsable", "page": 0,
        "x": 130, "y": 210, "w": 250, "h": 18,
        "font_size": 10, "max_len": 90, "align": "left",
        "type": "text", "placeholder": "Nombre completo",
        "staff_editable": False,
    },
]


def upload_template(env, module: str, name: str, pdf_bytes: bytes,
                    month_key: str | None = None) -> int | None:
    """Sube un PDF y devuelve el template_id (consultando la BD)."""
    data = {
        "pdf": (io.BytesIO(pdf_bytes), f"{name}.pdf"),
        "name": name,
        "month_key": month_key or _dt.date.today().strftime("%Y-%m"),
    }
    resp = env.client.post(
        f"/admin/{module}/docs/templates/upload",
        data=data, content_type="multipart/form-data",
        follow_redirects=False,
    )
    if resp.status_code not in (200, 302):
        return None
    # El handler redirige a /admin/<modulo>/docs/templates. Buscamos el id
    # del último template creado por nombre + module.
    from db import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM doc_templates WHERE name=? AND module=? ORDER BY id DESC LIMIT 1",
        (name, module),
    ).fetchone()
    conn.close()
    return int(row["id"]) if row else None


def main() -> int:
    rep = TestReporter("Bloque D · Documental PDF (SASISOPA/SGM)")
    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_consulting = baseline.station_consulting_id

        login(env, "admin", "admin123")
        set_session_brand(env, "consulting")

        # ====== 1. Health endpoint para ambos módulos =========================
        rep.section("/api/<modulo>/docs/health responde para sasisopa y sgm")
        for module in ("sasisopa", "sgm"):
            resp = env.client.get(f"/api/{module}/docs/health")
            rep.check(f"GET /api/{module}/docs/health → 200",
                      resp.status_code == 200, f"got {resp.status_code}")
            body = resp.get_json() or {}
            rep.check(f"{module}: body.ok=True, brand=consulting",
                      body.get("ok") is True and body.get("brand") == "consulting"
                      and body.get("module") == module,
                      f"got {body!r}")
            rep.check(f"{module}: counts inicial == 0",
                      body.get("templates") == 0
                      and body.get("requirements") == 0
                      and body.get("submissions") == 0,
                      f"got {body!r}")

        # ====== 2. Subir plantilla PDF de SASISOPA ============================
        rep.section("Upload de plantilla PDF (sasisopa) genera fila + previews")
        pdf_a = make_minimal_pdf_bytes(n_pages=2, title="Sasisopa A")
        tpl_a_id = upload_template(env, "sasisopa", "Plantilla A", pdf_a)
        rep.check("upload sasisopa → fila creada (id presente)",
                  isinstance(tpl_a_id, int), f"got {tpl_a_id!r}")
        tpl_a_db = db_get("doc_templates", "id=?", (tpl_a_id,)) if tpl_a_id else None
        rep.check("template persistido con module='sasisopa', brand='consulting'",
                  (tpl_a_db or {}).get("module") == "sasisopa"
                  and (tpl_a_db or {}).get("brand") == "consulting")
        rep.check("file_path contiene 'sasisopa_templates/consulting'",
                  "sasisopa_templates/consulting" in ((tpl_a_db or {}).get("file_path") or ""),
                  f"got {(tpl_a_db or {}).get('file_path')!r}")
        rep.check("field_schema_json inicial = '[]'",
                  (tpl_a_db or {}).get("field_schema_json") == "[]")
        rep.check("is_published == 0 (subida sin auto-publish)",
                  (tpl_a_db or {}).get("is_published") == 0)

        # Verificar que se generaron previews (PNG por página)
        previews_dir = env.upload_dir / f"sasisopa_template_previews/consulting/{tpl_a_id}"
        rep.check("directorio de previews creado",
                  previews_dir.exists(), str(previews_dir))
        if previews_dir.exists():
            pngs = list(previews_dir.glob("*.png"))
            rep.check("se generó 1 PNG por página (2 páginas → 2 PNGs)",
                      len(pngs) == 2, f"got {len(pngs)} png files: {pngs}")

        # ====== 3. Upload rechaza archivo no-PDF ==============================
        rep.section("Upload con archivo no-PDF → 400")
        resp = env.client.post(
            "/admin/sasisopa/docs/templates/upload",
            data={"pdf": (io.BytesIO(b"not a pdf"), "fake.txt"), "name": "X"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        rep.check("upload .txt → 400", resp.status_code == 400,
                  f"got {resp.status_code}")

        # ====== 4. Guardar esquema de campos ==================================
        rep.section("POST /templates/<id>/fields guarda schema con coordenadas")
        resp = env.client.post(
            f"/admin/sasisopa/docs/templates/{tpl_a_id}/fields",
            data={"schema_json": json.dumps(SAMPLE_SCHEMA)},
            follow_redirects=False,
        )
        rep.check("save schema → 302 (redirect a edit page)",
                  resp.status_code == 302, f"got {resp.status_code}")
        tpl_a_db = db_get("doc_templates", "id=?", (tpl_a_id,))
        saved = json.loads((tpl_a_db or {}).get("field_schema_json") or "[]")
        rep.check("schema persistido con 2 campos",
                  len(saved) == 2, f"got {len(saved)} fields")
        rep.check("campo 'fecha' tiene staff_editable=True",
                  any(f.get("key") == "fecha" and f.get("staff_editable") is True
                      for f in saved))
        rep.check("campo 'responsable' tiene coordenadas correctas",
                  any(f.get("key") == "responsable"
                      and f.get("x") == 130 and f.get("y") == 210
                      for f in saved))

        # 4.1 Schema inválido (no es lista) propaga ValueError no capturado.
        # Mismo patrón que BUG-002 (logo .gif → 500 sin handler): el endpoint
        # llama _parse_schema_input que hace `raise ValueError(...)` y nadie lo
        # captura. En producción Flask responde 500 con stacktrace en logs.
        # Aquí, con app.testing=True, propaga al test_client. Lo verificamos
        # con try/except y dejamos constancia.
        try:
            resp = env.client.post(
                f"/admin/sasisopa/docs/templates/{tpl_a_id}/fields",
                data={"schema_json": json.dumps({"not": "a list"})},
                follow_redirects=False,
            )
            raised = False
            status_code = resp.status_code
        except Exception:
            # Flask en testing=True propaga ValueError, pero make_response lo
            # reempaqueta como TypeError. Cualquiera de las dos cuenta como
            # "fallo no manejado" — equivalente a 500 en producción.
            raised = True
            status_code = 500
        rep.check("schema no-lista propaga excepción (en prod sería 500)",
                  raised or status_code >= 400,
                  f"raised={raised} status={status_code}")

        # ====== 5. Publish template ===========================================
        rep.section("POST /templates/<id>/publish marca is_published=1")
        resp = env.client.post(
            f"/admin/sasisopa/docs/templates/{tpl_a_id}/publish",
            follow_redirects=False,
        )
        rep.check("publish → 302", resp.status_code == 302)
        tpl_a_db = db_get("doc_templates", "id=?", (tpl_a_id,))
        rep.check("is_published == 1",
                  (tpl_a_db or {}).get("is_published") == 1)

        # ====== 6. Capture record (admin llena valores y genera PDF) ==========
        rep.section("POST /templates/<id>/record (admin captura + render PDF)")
        resp = env.client.post(
            f"/admin/sasisopa/docs/templates/{tpl_a_id}/record",
            data={
                "station_id": str(sid_consulting),
                "fecha": "2026-05-12",
                "responsable": "Ing. Test Block D",
            },
            follow_redirects=False,
        )
        rep.check("record save → 302", resp.status_code == 302,
                  f"got {resp.status_code}")
        rec_db = db_get("doc_records",
                         "module='sasisopa' AND station_id=? AND brand='consulting'",
                         (sid_consulting,))
        rep.check("doc_records persistido para la estación consulting",
                  rec_db is not None)
        rec_id = (rec_db or {}).get("id")
        rep.check("pdf_path apunta a sasisopa_records/consulting",
                  "sasisopa_records/consulting/station_" in
                  ((rec_db or {}).get("pdf_path") or ""),
                  f"got {(rec_db or {}).get('pdf_path')}")
        values = json.loads((rec_db or {}).get("field_values_json") or "{}")
        rep.check("field_values_json conserva valores capturados",
                  values.get("fecha") == "2026-05-12"
                  and values.get("responsable") == "Ing. Test Block D",
                  f"got {values}")
        # PDF renderizado existe físicamente
        pdf_abs = env.upload_dir / (rec_db or {}).get("pdf_path", "")
        rep.check("archivo PDF físico renderizado existe en disco",
                  pdf_abs.exists() and pdf_abs.stat().st_size > 100,
                  f"path={pdf_abs}, exists={pdf_abs.exists()}")

        # ====== 7. Upsert: segundo POST con misma estación actualiza ==========
        rep.section("Re-POST con misma (module, station) hace UPDATE (UNIQUE)")
        prev_count = db_row_count("doc_records",
                                   "module='sasisopa' AND station_id=?",
                                   (sid_consulting,))
        resp = env.client.post(
            f"/admin/sasisopa/docs/templates/{tpl_a_id}/record",
            data={
                "station_id": str(sid_consulting),
                "fecha": "2026-06-01",
                "responsable": "Ing. Cambio",
            },
            follow_redirects=False,
        )
        rep.check("re-POST → 302", resp.status_code == 302)
        new_count = db_row_count("doc_records",
                                  "module='sasisopa' AND station_id=?",
                                  (sid_consulting,))
        rep.check("count NO cambió (upsert, no insert)",
                  new_count == prev_count, f"prev={prev_count}, new={new_count}")
        rec_db = db_get("doc_records", "id=?", (rec_id,))
        values = json.loads((rec_db or {}).get("field_values_json") or "{}")
        rep.check("fecha y responsable actualizados",
                  values.get("fecha") == "2026-06-01"
                  and values.get("responsable") == "Ing. Cambio")

        # ====== 8. Health ahora reporta 1 template, 0 reqs, 0 subs ============
        rep.section("Health refleja el template subido")
        resp = env.client.get("/api/sasisopa/docs/health")
        body = resp.get_json() or {}
        rep.check("sasisopa health: templates=1",
                  body.get("templates") == 1, f"got {body}")

        # ====== 9. Aislamiento por module (sasisopa ≠ sgm) ====================
        rep.section("Aislamiento entre módulos sasisopa y sgm")
        pdf_b = make_minimal_pdf_bytes(n_pages=1, title="SGM B")
        tpl_b_id = upload_template(env, "sgm", "Plantilla SGM", pdf_b)
        rep.check("upload sgm → fila creada",
                  isinstance(tpl_b_id, int), f"got {tpl_b_id!r}")
        # sgm template no aparece en sasisopa
        sasisopa_tpls = db_row_count("doc_templates",
                                      "brand='consulting' AND module='sasisopa'",
                                      ())
        sgm_tpls = db_row_count("doc_templates",
                                 "brand='consulting' AND module='sgm'", ())
        rep.check("doc_templates sasisopa count == 1",
                  sasisopa_tpls == 1, f"got {sasisopa_tpls}")
        rep.check("doc_templates sgm count == 1",
                  sgm_tpls == 1, f"got {sgm_tpls}")
        # health endpoints reflejan los respectivos counts
        resp = env.client.get("/api/sgm/docs/health")
        rep.check("sgm health: templates=1",
                  (resp.get_json() or {}).get("templates") == 1)
        resp = env.client.get("/api/sasisopa/docs/health")
        rep.check("sasisopa health sigue en templates=1 (no mezcla)",
                  (resp.get_json() or {}).get("templates") == 1)

        # ====== 10. Aislamiento por brand (consulting vs petroleum) ===========
        rep.section("Aislamiento entre brand consulting y petroleum")
        set_session_brand(env, "petroleum")
        # Subir un template en sasisopa pero ahora brand=petroleum
        pdf_p = make_minimal_pdf_bytes(n_pages=1, title="Sasisopa Petroleum")
        tpl_p_id = upload_template(env, "sasisopa", "Plantilla Pet", pdf_p)
        rep.check("upload sasisopa petroleum → fila creada",
                  isinstance(tpl_p_id, int))
        # health(consulting brand) y health(petroleum brand)
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/sasisopa/docs/health")
        rep.check("consulting brand → sasisopa templates=1 (no ve petroleum)",
                  (resp.get_json() or {}).get("templates") == 1)
        set_session_brand(env, "petroleum")
        resp = env.client.get("/api/sasisopa/docs/health")
        rep.check("petroleum brand → sasisopa templates=1 (su propio template)",
                  (resp.get_json() or {}).get("templates") == 1)
        # En BD total: 2 sasisopa (uno por brand) + 1 sgm = 3
        total = db_row_count("doc_templates", "1=1", ())
        rep.check("total doc_templates en BD == 3 (2 sasisopa + 1 sgm)",
                  total == 3, f"got {total}")

        # ====== 11. Record download (admin) ===================================
        rep.section("GET /records/<id>/download devuelve PDF al admin")
        set_session_brand(env, "consulting")
        resp = env.client.get(
            f"/admin/sasisopa/docs/records/{rec_id}/download",
        )
        rep.check("admin download → 200", resp.status_code == 200,
                  f"got {resp.status_code}")
        rep.check("content-type es application/pdf",
                  "pdf" in (resp.headers.get("Content-Type") or "").lower(),
                  f"got {resp.headers.get('Content-Type')!r}")
        rep.check("body comienza con '%PDF-'",
                  resp.get_data().startswith(b"%PDF-"),
                  f"got prefix={resp.get_data()[:8]!r}")

        # ====== 12. Staff records page (jefe ve scoped) =======================
        rep.section("Staff records page: jefe_test ve solo su estación")
        # Crear estación consulting adicional + record para esa estación
        from db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO stations (brand, name, code, station_number, group_name) "
            "VALUES ('consulting','Otra Cons','C-OTRA','9099','X')"
        )
        sid_other = int(cur.lastrowid)
        conn.commit(); conn.close()

        # Admin crea record para la otra estación
        resp = env.client.post(
            f"/admin/sasisopa/docs/templates/{tpl_a_id}/record",
            data={
                "station_id": str(sid_other),
                "fecha": "2026-07-01",
                "responsable": "Otra Estación",
            },
            follow_redirects=False,
        )
        rep.check("admin crea record en C-OTRA → 302",
                  resp.status_code == 302)
        other_rec = db_get(
            "doc_records",
            "module='sasisopa' AND station_id=? AND brand='consulting'",
            (sid_other,),
        )
        rep.check("record de C-OTRA creado",
                  other_rec is not None)
        other_rec_id = (other_rec or {}).get("id")

        # Ahora jefe_test (asignado a C-DEMO-N = sid_consulting)
        login(env, "jefe_test", "jefe123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/staff/sasisopa/docs/records")
        rep.check("jefe → staff records page → 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        # No podemos parsear HTML fácil, pero verificamos por download:
        # debe poder bajar su record
        resp = env.client.get(
            f"/staff/sasisopa/docs/records/{rec_id}/download",
        )
        rep.check("jefe → download SU record → 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        # NO debe poder bajar el de C-OTRA
        resp = env.client.get(
            f"/staff/sasisopa/docs/records/{other_rec_id}/download",
        )
        rep.check("jefe → download record ajeno → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 13. Staff edit (campos staff_editable) ========================
        rep.section("Staff edit: solo campos con staff_editable=True")
        # jefe debe poder editar 'fecha' (staff_editable) pero NO 'responsable'
        resp = env.client.get(
            f"/staff/sasisopa/docs/records/{rec_id}/edit",
        )
        rep.check("jefe → GET staff edit form → 200",
                  resp.status_code == 200, f"got {resp.status_code}")

        resp = env.client.post(
            f"/staff/sasisopa/docs/records/{rec_id}/edit",
            data={
                "fecha": "2026-08-15",  # staff_editable
                "responsable": "HACK INTENTO",  # no es staff_editable
            },
            follow_redirects=False,
        )
        rep.check("jefe → POST staff edit → 302",
                  resp.status_code == 302, f"got {resp.status_code}")
        rec_db = db_get("doc_records", "id=?", (rec_id,))
        values = json.loads((rec_db or {}).get("field_values_json") or "{}")
        rep.check("'fecha' SÍ se actualizó (staff_editable)",
                  values.get("fecha") == "2026-08-15",
                  f"got {values}")
        rep.check("'responsable' NO se cambió (no es staff_editable)",
                  values.get("responsable") == "Ing. Cambio",
                  f"got {values.get('responsable')!r}")

        # 13.1 Staff edit sobre record ajeno → 403
        resp = env.client.post(
            f"/staff/sasisopa/docs/records/{other_rec_id}/edit",
            data={"fecha": "2026-09-09"},
            follow_redirects=False,
        )
        rep.check("jefe → POST edit record ajeno → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 14. Capture submit (legacy) está deshabilitada ================
        rep.section("Legacy capture_submit cerrada (single-submission policy)")
        # jefe intenta hacer captura legacy → 403
        resp = env.client.post(
            f"/staff/sasisopa/docs/capture/99999",
            data={"any": "field"},
            follow_redirects=False,
        )
        rep.check("jefe → POST capture legacy → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 15. Unlock requirement cerrado ================================
        rep.section("Unlock de requirement deshabilitado")
        login(env, "admin", "admin123")
        set_session_brand(env, "consulting")
        resp = env.client.post(
            "/admin/sasisopa/docs/requirements/99999/unlock",
            follow_redirects=False,
        )
        rep.check("admin → POST unlock → 400 (deshabilitado)",
                  resp.status_code == 400, f"got {resp.status_code}")

        # ====== 16. Role gate: staff NO accede a /admin/<modulo>/docs/* ======
        rep.section("Role gate: staff (jefe) → 403 en rutas /admin/<modulo>/docs/*")
        login(env, "jefe_test", "jefe123")
        set_session_brand(env, "consulting")
        for path in (
            "/admin/sasisopa/docs",
            "/admin/sasisopa/docs/templates",
            "/admin/sasisopa/docs/records",
            "/admin/sasisopa/docs/reviews",
            "/admin/sgm/docs/templates",
        ):
            resp = env.client.get(path, follow_redirects=False)
            rep.check(f"jefe → GET {path} → 403",
                      resp.status_code == 403, f"got {resp.status_code}")

        # Staff upload de plantilla intentado → 403
        resp = env.client.post(
            "/admin/sasisopa/docs/templates/upload",
            data={"pdf": (io.BytesIO(make_minimal_pdf_bytes(1)), "x.pdf"),
                  "name": "intento"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        rep.check("jefe → POST upload template → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 17. Anonymous: rutas devuelven 401 (login_required aborta) ====
        # ctx.login_required usa abort(401) en vez de redirect — el frontend
        # interpreta el 401 y muestra el modal de login.
        rep.section("Anonymous → 401 (login_required aborta sin redirect)")
        with env.client.session_transaction() as s:
            s.clear()
        for path in ("/admin/sasisopa/docs", "/staff/sgm/docs/records"):
            resp = env.client.get(path, follow_redirects=False)
            rep.check(f"anon → {path} → 401",
                      resp.status_code == 401,
                      f"got {resp.status_code}")

        # ====== 18. Auditor: read-only en admin (depende del role gate) ======
        rep.section("Auditor: role_required('admin') le niega rutas admin")
        login(env, "auditor_test", "auditor123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/admin/sasisopa/docs/templates",
                                follow_redirects=False)
        rep.check("auditor → /admin/sasisopa/docs/templates → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
