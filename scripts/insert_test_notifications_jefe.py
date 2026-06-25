import sqlite3
import datetime

DB_PATH = "data/cog_work_log.db"
BRAND = "consulting"
JEFE_USERNAME = "jose"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Buscar al jefe de estacion
cur.execute(
    "SELECT id, username, role, station_id FROM users WHERE username=? AND is_active=1 LIMIT 1",
    (JEFE_USERNAME,)
)
jefe = cur.fetchone()
if not jefe:
    print(f"ERROR: usuario '{JEFE_USERNAME}' no encontrado")
    conn.close()
    exit(1)

jefe_id = int(jefe["id"])
station_id = int(jefe["station_id"]) if jefe["station_id"] else None
print(f"Jefe encontrado -> id={jefe_id}, username={jefe['username']}, role={jefe['role']}, station_id={station_id}")

# 2. Obtener nombre de estacion para mensajes mas descriptivos
station_name = f"Estacion {station_id}"
if station_id:
    cur.execute("SELECT name, code FROM stations WHERE id=?", (station_id,))
    st = cur.fetchone()
    if st:
        station_name = f"{st['name']} ({st['code']})"
print(f"Estacion: {station_name}")

# 3. Limpiar notificaciones de prueba anteriores
cur.execute(
    "DELETE FROM notifications WHERE brand=? AND user_id=? AND title LIKE '[PRUEBA]%'",
    (BRAND, jefe_id)
)
print("Notificaciones de prueba previas eliminadas.")

# 4. Insertar notificaciones de prueba segun los tipos del jefe_estacion
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

notifs = [
    {
        "ntype": "doc_due",
        "title": "[PRUEBA] Documentacion local por vencer",
        "body": f"SASISOPA: Licencia Ambiental · vence en 3 dias · {station_name}",
        "url": "/staff/sasisopa/docs",
    },
    {
        "ntype": "submission",
        "title": "[PRUEBA] Nueva evidencia subida",
        "body": f"El operador 'operador1' subio evidencia para Evento #42 en {station_name}. Requiere validacion.",
        "url": "/mod/station-evidence",
    },
    {
        "ntype": "due",
        "title": "[PRUEBA] Retraso en tareas del dia",
        "body": f"3 actividades del calendario operacional estan vencidas sin entrega en {station_name}.",
        "url": "/mod/operational-calendar",
    },
    {
        "ntype": "incident",
        "title": "[PRUEBA] Incidencia reportada en tu estacion",
        "body": f"operador1 reporto: 'Falla en bomba #2, no despacha gasolina premium' — {station_name}. Severidad: alta.",
        "url": "/mod/incidents",
    },
]

inserted = 0
for n in notifs:
    cur.execute(
        "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url, is_read, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (BRAND, jefe_id, station_id, n["ntype"], n["title"], n["body"], n["url"], now)
    )
    inserted += 1
    print(f"  Insertada: [{n['ntype']}] {n['title']}")

conn.commit()
conn.close()

print(f"\nListo. {inserted} notificaciones de prueba insertadas para '{JEFE_USERNAME}' (brand={BRAND}, station_id={station_id}).")
print(f"Inicia sesion como '{JEFE_USERNAME}' y ve a /mod/notifications para verlas.")
