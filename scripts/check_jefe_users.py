import sqlite3

conn = sqlite3.connect("data/cog_work_log.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute(
    "SELECT id, username, role, station_id, brand FROM users WHERE role='jefe_estacion' AND is_active=1 LIMIT 10"
)
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"id={r['id']} username={r['username']} role={r['role']} station_id={r['station_id']} brand={r['brand']}")
else:
    print("No hay usuarios jefe_estacion activos")

# Tambien mostrar las estaciones disponibles
print("\n--- Estaciones disponibles ---")
cur.execute("SELECT id, name, code, brand FROM stations WHERE brand='consulting' ORDER BY id LIMIT 10")
for s in cur.fetchall():
    print(f"station id={s['id']} code={s['code']} name={s['name']} brand={s['brand']}")

conn.close()
