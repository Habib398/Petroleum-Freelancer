import sqlite3
import datetime

DB_PATH = "data/cog_work_log.db"
BRAND = "consulting"
ADMIN_USERNAME = "admin"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Buscar admin
cur.execute("SELECT id, username, role FROM users WHERE username=? LIMIT 1", (ADMIN_USERNAME,))
admin = cur.fetchone()
if not admin:
    print("ERROR: usuario admin no encontrado")
    conn.close()
    exit(1)

admin_id = int(admin["id"])
print(f"Admin encontrado -> id={admin_id}, username={admin['username']}, role={admin['role']}")

# 2. Borrar notificaciones de prueba anteriores para no acumular basura
cur.execute(
    "DELETE FROM notifications WHERE brand=? AND user_id=? AND title LIKE '[PRUEBA]%'",
    (BRAND, admin_id)
)
print(f"Notificaciones de prueba previas eliminadas.")

# 3. Insertar notificaciones de prueba para cada tipo del admin
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

notifs = [
    {
        "ntype": "audit",
        "title": "[PRUEBA] Alerta de Auditoría",
        "body": "El usuario 'operador1' realizó un cambio de contraseña en el sistema.",
        "url": "/admin/audit",
    },
    {
        "ntype": "doc_due",
        "title": "[PRUEBA] Documento por vencer",
        "body": "SASISOPA: Permiso CRE · vence 2026-06-25 · Estación Norte",
        "url": "/admin/sasisopa/docs/reviews",
    },
    {
        "ntype": "incident",
        "title": "[PRUEBA] Problema Recurrente reportado",
        "body": "Operador reportó falla en bomba #3 — Estación Centro. Severidad: alta.",
        "url": "/mod/incidents",
    },
    {
        "ntype": "backup",
        "title": "[PRUEBA] Respaldo automático completado",
        "body": "Respaldo diario creado exitosamente: cog_backup_20260618.zip",
        "url": "/admin/backup",
    },
]

inserted = 0
for n in notifs:
    cur.execute(
        "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url, is_read, created_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, 0, ?)",
        (BRAND, admin_id, n["ntype"], n["title"], n["body"], n["url"], now)
    )
    inserted += 1
    print(f"  Insertada: [{n['ntype']}] {n['title']}")

conn.commit()
conn.close()
print(f"\nListo. {inserted} notificaciones de prueba insertadas para '{ADMIN_USERNAME}' (brand={BRAND}).")
print("Inicia sesion como admin y ve a /mod/notifications para verlas.")
