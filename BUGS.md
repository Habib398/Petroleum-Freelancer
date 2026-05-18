# Registro de bugs

Bugs detectados durante las pruebas automatizadas (`scripts/tests/`). Se añaden
en orden cronológico. Cada bug tiene un ID único `BUG-NNN` que persiste aunque
cambien orden o estado.

## Convenciones

| Estado | Significado |
|---|---|
| 🔴 ABIERTO | Detectado, sin arreglar |
| 🟡 EN PROGRESO | Siendo investigado / corregido |
| 🟢 ARREGLADO | Fix aplicado y test que lo detectó ahora pasa |
| ⚪ DESCARTADO | Resultó no ser bug / fuera de alcance |

Severidad:

- **Alta**: vulnerabilidad de seguridad, pérdida o corrupción de datos, bloquea uso.
- **Media**: feature roto pero hay workaround, o impacto limitado.
- **Baja**: cosmético, edge case raro, no bloquea uso.

---

## BUG-001 · Cross-station write en `POST /api/compliance/item/<code>/status`

| Campo | Valor |
|---|---|
| Fecha detección | 2026-05-09 |
| Fecha fix | 2026-05-09 |
| Severidad | Alta |
| Estado | 🟢 ARREGLADO |
| Detectado por | Bloque I · sección 8 (cross-station write rejection) |
| Endpoint | `POST /api/compliance/item/<code>/status` |
| Archivo | [modules/compliance/compliance.py:212](modules/compliance/compliance.py#L212) |

**Resumen**: El endpoint acepta `station_id` en el body y escribe a `compliance_records` sin validar que el usuario tenga acceso a esa estación. Un `jefe_estacion` podía modificar el estatus de cumplimiento de **cualquier** estación petroleum (no solo de la suya). Además, el decorador `@role_required("admin", "jefe_estacion", "auditor")` permitía que un `auditor` escribiera, cuando solo debería leer.

**Evidencia**: jefe_pet (asignado a `P-DEMO`, group `Demo`) hizo POST con `station_id=<P-EXTRA>` (otra estación sin group) → respondió `200 ok` cuando debió ser `403 forbidden`.

**Endpoint hermano que SÍ validaba**: `GET /api/compliance/items` ([compliance.py:59](modules/compliance/compliance.py#L59)) usa la misma lógica de scope (jefe ve estaciones del mismo `group_name`). La validación no se había replicado en el POST.

**Fix aplicado**:
1. Quitado `"auditor"` del `@role_required` — ahora solo `admin` y `jefe_estacion` pueden escribir.
2. Agregado bloque de validación de scope antes del INSERT: replica la lógica del GET (jefe_estacion sólo puede tocar estaciones petroleum de su mismo `group_name`; otros no-admin sólo su propia estación).
3. Si `station_id` no está en el set permitido → `403 forbidden`.

**Verificación**: Bloque I · sección 8 pasó tras el fix (35/35 OK).

---

## BUG-002 · Logo con extensión inválida devuelve 500 en vez de 400

| Campo | Valor |
|---|---|
| Fecha detección | 2026-05-10 |
| Severidad | Baja (cosmético / operativo) |
| Estado | 🔴 ABIERTO |
| Detectado por | Bloque B · sección 6 (logo con extensión inválida es rechazado) |
| Endpoint | `POST /api/profile` |
| Archivo | [modules/auth/profile.py:79-82](modules/auth/profile.py#L79) |

**Resumen**: Cuando un admin sube un logo con extensión inválida (ej. `.gif`), `ctx.save_upload_checked` levanta `ValueError("invalid_file_type")` que no es capturado por el endpoint. Llega al manejador global de Flask y se responde como **500 server_error** con stacktrace en los logs (`ERROR in app: Unhandled exception`), cuando debería ser un **400 bad_request** limpio con un mensaje útil.

**Impacto**: La validación funciona — el archivo malo no se persiste y `logo_*_path` no se sobrescribe. Pero los logs se llenan de tracebacks cuando alguien sube un tipo no permitido, dificultando el monitoreo de errores reales.

**Introducido por**: el agregado de uploads de logos durante los quick wins (`logo_empresa` / `logo_estacion`). Los uploads de FIEL (cer/key) tienen el mismo patrón pero rara vez se ejecutan con extensión inválida.

**Fix sugerido**: envolver las llamadas a `save_upload_checked` en try/except dentro del endpoint y devolver 400 con `{"error": "invalid_file_type", "message": "Tipo de archivo no permitido para logo_*"}`.

---

## BUG-003 · `sync_document_deadlines` no commitea, los GET pierden los cambios al cerrar conexión

| Campo | Valor |
|---|---|
| Fecha detección | 2026-05-10 |
| Fecha fix | 2026-05-10 |
| Severidad | Media (datos inconsistentes en condiciones de carrera; oculto en uso normal) |
| Estado | 🟢 ARREGLADO |
| Detectado por | Bloque E · sección 12 (jefe NO puede renovar deadline de otra estación) |
| Archivo | [services/deadlines.py:103](services/deadlines.py#L103) |

**Resumen**: `sync_document_deadlines(conn, brand)` actualiza la tabla `document_deadlines` con INSERT/UPDATE/DELETE desde `normativas`, `tramites` y `expediente_records`, pero **nunca hace `conn.commit()`**. Los endpoints GET que lo llaman (`/api/document-deadlines`, `/api/document-renewals-calendar`, `/api/document-deadlines/export.csv`) ven los datos en memoria dentro de la misma conexión, pero al cerrar la conexión sin commit, los cambios se rollback.

**Por qué normalmente "funciona"**: los endpoints POST que crean/modifican normativas/tramites (`POST /api/normativas`, etc.) sí hacen `conn.commit()` después de llamar sync. Y `run_due_tick` (que corre vía `_scheduled_ticks` después de cada request /api/ o /admin) sí commitea (línea 693 de `services/scheduled.py`). En la mayoría de los flujos de la UI, sync se ejecuta y persiste por uno de esos dos caminos. Pero `run_due_tick` tiene throttle de **15 min** — si se ejecutó recientemente, se salta.

**Cuándo aparece el bug**: cuando una normativa/trámite/expediente se crea por una ruta que **no commitea sync** (ej. inserción directa por SQL, importación masiva, scripts de mantenimiento). El deadline queda invisible en la tabla `document_deadlines` hasta que `run_due_tick` se libere del throttle (≥15 min después).

**Evidencia**: Bloque E sección 12 inserta una normativa por SQL directo, después admin hace `GET /api/document-deadlines` y la ve en la respuesta. Pero un `db_get("document_deadlines", "id=? AND brand=?", ...)` en paralelo retorna `None`. Luego un `POST /renew` con ese ID devuelve `404 not_found` porque el `SELECT` interno no la encuentra.

**Fix aplicado**: agregado `conn.commit()` al final de `sync_document_deadlines` antes del `return total`, envuelto en try/except por si el caller ya cerró la conn (defensa en profundidad). Es idempotente — los callers que ya commiten quedan igual; los GET que no commiten ahora persisten correctamente.

**Verificación**:
- Bloque E pasó 52/52 OK tras el fix (incluyendo la sección 12 que fallaba).
- Regresión: Pre-0, A, I, B siguen pasando todos sus checks (208/208 total).

---

## BUG-004 · Schema inválido en `POST /admin/<modulo>/docs/templates/<id>/fields` propaga ValueError

| Campo | Valor |
|---|---|
| Fecha detección | 2026-05-12 |
| Severidad | Baja (cosmético / operativo) |
| Estado | 🔴 ABIERTO |
| Detectado por | Bloque D · sección 4 (POST /templates/<id>/fields con schema no-lista) |
| Endpoint | `POST /admin/<modulo>/docs/templates/<id>/fields` |
| Archivo | [modules/compliance/documental_docs.py:611-617](modules/compliance/documental_docs.py#L611) |

**Resumen**: El handler `save_fields` llama `_parse_schema_input(...)` sin envolverlo en try/except. Si el JSON enviado no es una lista (ej. un dict), `_parse_schema_input` levanta `ValueError("El esquema debe ser una lista JSON")`, que **no se captura**. Llega al manejador global de Flask y se responde como **500 server_error** con stacktrace en los logs.

**Mismo patrón que BUG-002** (logo con extensión inválida): la validación funciona — el esquema malo no se persiste — pero los logs se llenan de tracebacks (`ERROR in app: Unhandled exception ... ValueError: El esquema debe ser una lista JSON`).

**Impacto**: La UI hoy serializa siempre una lista, así que en operación normal nunca se dispara. Pero si un admin pega manualmente un dict en el editor o si un script externo manda payload mal formado, los logs ensucian el monitoreo.

**Fix sugerido**: envolver la llamada en try/except y devolver 400 con `{"error": "invalid_schema", "message": "El esquema debe ser una lista JSON"}`, o renderizar la página de edición con un banner de error.

**Aplica también a SGM**: la fábrica `register_module` registra las mismas rutas para `module_key='sasisopa'` y `module_key='sgm'`, así que la misma vulnerabilidad cosmética está en `/admin/sgm/docs/templates/<id>/fields`.
