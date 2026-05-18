"""Bloque B · Datos privados de estación

Verifica que el endpoint ``/api/profile`` y la tabla ``station_profiles``
(enriquecida en los quick wins) funcionan correctamente para:

* GET por admin y por jefe (con scoping de estación).
* POST partial update — sólo se modifican los campos enviados.
* POST full update — todos los campos a la vez.
* Subida de logos (PNG/JPG) y rechazo de extensiones inválidas.
* Bloqueo a roles no-admin (403).
* Bloqueo cuando falta ``station_id`` (400).
* Verificación end-to-end: los datos privados llegan al ``resolve_auto_values``
  del motor DOCX para alimentar el autollenado de plantillas (cap. 5 + cap. 6
  de la propuesta).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    STATION_CONSULTING_PROFILE,
    STATION_PETROLEUM_PROFILE,
    db_get,
    login,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


# Cabeceras mágicas mínimas para que las pruebas envíen "imágenes" reconocibles
# si en algún momento se activa validación magic-bytes en el endpoint. Por
# ahora la validación es solo por extensión, pero mantener bytes válidos hace
# el test robusto a futuros endurecimientos.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32


def main() -> int:
    rep = TestReporter("Bloque B · Datos privados de estación")

    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_c = baseline.station_consulting_id
        sid_p = baseline.station_petroleum_id

        # ====== 1. GET /api/profile devuelve datos sembrados =================
        rep.section("GET /api/profile devuelve datos sembrados")
        rep.check("admin inicia sesión", login(env, "admin", "admin123"))
        resp = env.client.get(f"/api/profile?station_id={sid_c}")
        rep.check("GET consulting → 200", resp.status_code == 200,
                  f"got {resp.status_code}")
        body = resp.get_json() or {}
        prof = body.get("profile") or {}
        rep.check("profile incluye rfc esperado",
                  prof.get("rfc") == STATION_CONSULTING_PROFILE["rfc"],
                  f"got rfc={prof.get('rfc')!r}")
        rep.check("profile incluye permiso_cre esperado",
                  prof.get("permiso_cre") == STATION_CONSULTING_PROFILE["permiso_cre"])
        rep.check("profile incluye responsable_sasisopa esperado",
                  prof.get("responsable_sasisopa") == STATION_CONSULTING_PROFILE["responsable_sasisopa"])

        # Pedir el petroleum también
        resp = env.client.get(f"/api/profile?station_id={sid_p}")
        prof_p = (resp.get_json() or {}).get("profile") or {}
        rep.check("GET petroleum → datos petroleum correctos",
                  prof_p.get("rfc") == STATION_PETROLEUM_PROFILE["rfc"]
                  and prof_p.get("permiso_cre") == STATION_PETROLEUM_PROFILE["permiso_cre"],
                  f"got rfc={prof_p.get('rfc')!r}")

        # ====== 2. GET con station_id inválido o ausente =====================
        rep.section("GET con station_id inválido / ausente")
        resp = env.client.get("/api/profile?station_id=abc")
        rep.check("station_id no numérico → 400",
                  resp.status_code == 400, f"got {resp.status_code}")

        # Admin sin station_id en la query y sin station_id propio → profile=None
        resp = env.client.get("/api/profile")
        body = resp.get_json() or {}
        rep.check("admin sin station_id → profile is None",
                  body.get("profile") is None, f"got body={body}")

        # ====== 3. POST partial update — solo se modifican campos enviados ==
        rep.section("POST partial update preserva los campos no enviados")
        # Capturar valor actual de responsable_sasisopa
        before = db_get("station_profiles", "station_id=?", (sid_c,))
        old_resp_sas = (before or {}).get("responsable_sasisopa")

        resp = env.client.post("/api/profile", data={
            "station_id": str(sid_c),
            "telefono": "55-9999-NEW",
        }, content_type="multipart/form-data")
        rep.check("POST partial → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        after = db_get("station_profiles", "station_id=?", (sid_c,))
        rep.check("teléfono fue actualizado",
                  (after or {}).get("telefono") == "55-9999-NEW",
                  f"got telefono={(after or {}).get('telefono')!r}")
        rep.check("responsable_sasisopa NO cambió (preservado por COALESCE)",
                  (after or {}).get("responsable_sasisopa") == old_resp_sas,
                  f"old={old_resp_sas!r}, new={(after or {}).get('responsable_sasisopa')!r}")

        # ====== 4. POST full update — todos los campos a la vez =============
        rep.section("POST full update actualiza todos los campos privados")
        full_data = {
            "station_id": str(sid_c),
            "permit_number": "PER/FULL/2026",
            "legal_name": "Razón Full S.A.",
            "rfc": "FUL260101AAA",
            "domicilio": "Calle Full 123",
            "permiso_cre": "PL/FULL/2026",
            "representante_legal": "Lic. Full",
            "responsable_operativo": "Ing. Full Op",
            "responsable_sasisopa": "Ing. Full Sas",
            "responsable_sgm": "Ing. Full Sgm",
            "correo": "full@example.com",
            "telefono": "55-FULL-0000",
        }
        resp = env.client.post("/api/profile", data=full_data,
                                content_type="multipart/form-data")
        rep.check("POST full → 200", resp.status_code == 200)
        row = db_get("station_profiles", "station_id=?", (sid_c,))
        for key, expected in full_data.items():
            if key == "station_id":
                continue
            rep.check(f"campo {key!r} guardado",
                      (row or {}).get(key) == expected,
                      f"expected {expected!r}, got {(row or {}).get(key)!r}")

        # ====== 5. Subir logos PNG/JPG ======================================
        rep.section("Logo PNG/JPG aceptados y persistidos")
        resp = env.client.post("/api/profile", data={
            "station_id": str(sid_c),
            "logo_empresa": (io.BytesIO(PNG_MAGIC), "marca.png"),
            "logo_estacion": (io.BytesIO(JPG_MAGIC), "sede.jpg"),
        }, content_type="multipart/form-data")
        rep.check("POST con logos → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        row = db_get("station_profiles", "station_id=?", (sid_c,))
        logo_emp = (row or {}).get("logo_empresa_path") or ""
        logo_est = (row or {}).get("logo_estacion_path") or ""
        rep.check("logo_empresa_path apunta a .png",
                  logo_emp.endswith(".png"), f"got {logo_emp!r}")
        rep.check("logo_estacion_path apunta a .jpg",
                  logo_est.endswith(".jpg"), f"got {logo_est!r}")
        rep.check("logo_empresa archivo existe en disco",
                  (env.upload_dir / logo_emp).exists(),
                  f"path={env.upload_dir / logo_emp}")
        rep.check("logo_estacion archivo existe en disco",
                  (env.upload_dir / logo_est).exists())

        # ====== 6. Logo con extensión inválida es rechazado =================
        rep.section("Logo con extensión inválida es rechazado")
        resp = env.client.post("/api/profile", data={
            "station_id": str(sid_c),
            "logo_empresa": (io.BytesIO(b"GIF89a..."), "malicioso.gif"),
        }, content_type="multipart/form-data")
        rep.check(".gif rechazado (status ≠ 200)",
                  resp.status_code != 200, f"got {resp.status_code}")
        # logo_empresa_path NO debe haber cambiado a algo .gif
        row = db_get("station_profiles", "station_id=?", (sid_c,))
        rep.check("logo_empresa_path sigue siendo .png (no se sobrescribió)",
                  ((row or {}).get("logo_empresa_path") or "").endswith(".png"),
                  f"got {(row or {}).get('logo_empresa_path')!r}")

        # ====== 7. POST por no-admin → 403 ==================================
        rep.section("POST no-admin → 403 forbidden")
        for username, password in (("jefe_test", "jefe123"),
                                    ("operador_test", "operador123"),
                                    ("auditor_test", "auditor123")):
            login(env, username, password)
            resp = env.client.post("/api/profile", data={
                "station_id": str(sid_c),
                "telefono": "55-HACK",
            }, content_type="multipart/form-data")
            rep.check(f"{username} → POST /api/profile devuelve 403",
                      resp.status_code == 403, f"got {resp.status_code}")

        # ====== 8. Admin sin station_id en POST → 400 =======================
        rep.section("Admin sin station_id en POST → 400")
        login(env, "admin", "admin123")
        resp = env.client.post("/api/profile", data={"rfc": "X"},
                                content_type="multipart/form-data")
        rep.check("POST sin station_id → 400",
                  resp.status_code == 400, f"got {resp.status_code}")

        # ====== 9. POST a estación que no existe → 404 ======================
        rep.section("POST a estación inexistente → 404")
        resp = env.client.post("/api/profile", data={
            "station_id": "99999",
            "rfc": "X",
        }, content_type="multipart/form-data")
        rep.check("POST con station_id=99999 → 404",
                  resp.status_code == 404, f"got {resp.status_code}")

        # ====== 10. Crear profile nuevo (estación sin profile previo) =======
        rep.section("Admin puede crear profile en estación sin profile previo")
        # Insertar estación nueva (sin profile)
        from db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO stations (brand, name, code) VALUES ('consulting','Nueva',?)",
            ("C-NEW",),
        )
        new_sid = int(cur.lastrowid)
        conn.commit(); conn.close()

        rep.check("estación nueva creada sin station_profile",
                  db_get("station_profiles", "station_id=?", (new_sid,)) is None)

        resp = env.client.post("/api/profile", data={
            "station_id": str(new_sid),
            "rfc": "NEW260101XYZ",
            "domicilio": "Nueva dirección",
        }, content_type="multipart/form-data")
        rep.check("POST a estación sin profile → 200 (crea fila nueva)",
                  resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        new_row = db_get("station_profiles", "station_id=?", (new_sid,))
        rep.check("nuevo station_profile fue creado",
                  new_row is not None)
        rep.check("rfc del profile nuevo es correcto",
                  (new_row or {}).get("rfc") == "NEW260101XYZ")

        # ====== 11. Verificación end-to-end: motor DOCX usa los datos ======
        # Esta es la razón principal de tener los datos privados: alimentar
        # el autollenado de plantillas DOCX.
        rep.section("Motor DOCX resuelve los datos privados como valores AUTO")
        from services.docx_variables import resolve_auto_values

        auto = resolve_auto_values(sid_c)
        rep.check("auto[RFC] = el valor full_update que escribimos",
                  auto.get("RFC") == "FUL260101AAA",
                  f"got auto[RFC]={auto.get('RFC')!r}")
        rep.check("auto[PERMISO_CRE] = el valor full_update",
                  auto.get("PERMISO_CRE") == "PL/FULL/2026")
        rep.check("auto[RESPONSABLE_SASISOPA] = el valor full_update",
                  auto.get("RESPONSABLE_SASISOPA") == "Ing. Full Sas")
        rep.check("auto[LOGO_EMPRESA] tiene la ruta del logo",
                  (auto.get("LOGO_EMPRESA") or "").endswith(".png"),
                  f"got auto[LOGO_EMPRESA]={auto.get('LOGO_EMPRESA')!r}")
        rep.check("auto[NOMBRE_ESTACION] viene de la tabla stations",
                  auto.get("NOMBRE_ESTACION") == "Estación Demo Norte",
                  f"got {auto.get('NOMBRE_ESTACION')!r}")

        # Para la estación NEW (sin override), todos los datos privados
        # vienen solo del INSERT que acabamos de hacer.
        auto_new = resolve_auto_values(new_sid)
        rep.check("auto[RFC] de la estación nueva refleja el INSERT",
                  auto_new.get("RFC") == "NEW260101XYZ")
        rep.check("auto[NOMBRE_ESTACION] de la estación nueva",
                  auto_new.get("NOMBRE_ESTACION") == "Nueva")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
