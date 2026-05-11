# Plan de pruebas — Work Log Control Documental

Fecha del plan: 2026-05-08
Versión del sistema: post quick-wins + motor DOCX

---

## Cómo usar este documento

Este plan está organizado en **bloques** (A, B, C…). Cada bloque agrupa pruebas de un área del sistema. Dentro de cada bloque hay **escenarios** numerados (A1, A2, B1…) con:

- **Quién prueba**: rol del usuario que ejecuta la prueba (admin / jefe / operador / auditor).
- **Pre-requisitos**: qué tiene que existir antes de empezar (datos, configuración).
- **Pasos**: en orden, qué clickear / qué hacer.
- **Resultado esperado**: qué debe pasar para considerar la prueba aprobada.

**Estado de cada bloque**:

- ✅ **Listo para probar** — implementado y validado por código.
- ⚠️ **Con limitaciones** — funciona pero hay vacíos conocidos.
- ❌ **NO probar todavía** — no implementado, omitir.

---

## Tabla de contenidos

| Bloque | Área | Estado |
|---|---|---|
| Pre-0 | Preparación de entorno | — |
| A | Autenticación y sesión | ✅ |
| B | Datos privados de estación (cap. 5) | ✅ |
| C | Plantillas DOCX nuevas (cap. 6) | ⚠️ sin UI todavía — vía script de demo |
| D | Plantillas PDF + coordenadas legacy (SASISOPA / SGM) | ✅ |
| E | Vencimientos y alertas (cap. 3.3) | ✅ |
| F | Expediente digital por estación (cap. 4) | ⚠️ sin export ZIP |
| G | Trámites y normativas (cap. 3) | ✅ |
| H | Petroleum: control de vigencias (cap. 7) | ✅ |
| I | Permisos y aislamiento por marca / estación | ✅ |
| J | Backups | ✅ |
| K | Auditoría (audit log) | ✅ |
| L | Bitácoras programadas (cap. 8) | ❌ NO probar |
| M | Export ZIP del expediente (cap. 4) | ❌ NO probar |

---

## Pre-0 · Preparación del entorno

### 0.1 Respaldo obligatorio antes de empezar

Antes de cualquier prueba destructiva, hacer un backup. Esto te permite restaurar si algo se daña.

1. Entrar a `Admin → Backups` (o llamar `POST /api/admin/backups/create` si pruebas vía API).
2. Confirmar que aparece un nuevo zip en `backups/`.
3. Verificar que la fila se registró en la tabla `backup_logs` (campo nuevo).

**Resultado esperado**: archivo `backups/backup_YYYYMMDD_HHMMSS.zip` creado y entrada en `backup_logs` con `kind='manual'` y `triggered_by=<tu user_id>`.

### 0.2 Usuarios de prueba a crear

El admin por defecto es `admin / admin123`. Para probar permisos necesitas además:

| Usuario | Rol | `primary_brand` | `station_id` | Para |
|---|---|---|---|---|
| jefe_test | jefe_estacion | consulting | (estación 1) | Probar aislamiento de jefe |
| jefe_pet | jefe_estacion | petroleum | (estación 2 petroleum) | Probar permisos petroleum |
| operador_test | operador | consulting | (estación 1) | Probar captura |
| auditor_test | auditor | consulting | NULL | Probar solo-lectura |

Crearlos desde `Admin → Usuarios`. Anotar las contraseñas.

### 0.3 Estaciones de prueba

Crear al menos:

- 1 estación `consulting` (ej. "Estación Demo Norte", code `C-DEMO-N`).
- 1 estación `petroleum` (ej. "Estación Demo Pet", code `P-DEMO`).

### 0.4 Datos privados de estación

Para cada estación, ir a `Admin → Mi estación → Datos privados` (o equivalente) y llenar:
RFC, domicilio, permiso CRE, representante legal, responsables SASISOPA/SGM/operativo, correo, teléfono, logo.

> Si todavía no hay UI específica para estos campos nuevos, hacerlo por API en Postman:
> `POST /api/profile` con multipart con los campos `rfc`, `domicilio`, `permiso_cre`, etc.
> (Está documentado el endpoint en [modules/auth/profile.py](modules/auth/profile.py).)

---

## Bloque A · Autenticación y sesión ✅

### A1 — Login admin

**Quién**: cualquier usuario.
**Pre-requisitos**: ninguno.

**Pasos**:
1. Ir a `/login`.
2. Username: `admin`, password: `admin123`.
3. Click "Entrar".

**Resultado esperado**: redirige al menú admin. La cookie de sesión queda activa. En la cabecera se ve el nombre de usuario.

### A2 — Login con credenciales inválidas

**Pasos**:
1. Ir a `/login`.
2. Username: `admin`, password: `incorrecto`.

**Resultado esperado**: error "credenciales inválidas". No redirige.

### A3 — Rate limit de login

**Pasos**:
1. Hacer 9 intentos fallidos seguidos con el mismo usuario.

**Resultado esperado**: a partir del intento 9 (límite=8 en 10 min) responde 429 *"Demasiados intentos"*.

### A4 — Logout

**Pasos**:
1. Estando logueado, click "Cerrar sesión".
2. Intentar acceder a `/admin/menu` directamente.

**Resultado esperado**: redirige a `/login`.

### A5 — Cambio de marca (consulting ↔ petroleum)

**Quién**: admin (tiene ambas marcas en `allowed_brands`).
**Pasos**:
1. Estando en consulting, ir a `/petroleum` (o cambiar desde el selector de marca).
2. Verificar que cambia el menú/colores.
3. Volver a consulting.

**Resultado esperado**: el sistema muestra solo datos de la marca activa. Estaciones petroleum no aparecen al estar en consulting y viceversa.

---

## Bloque B · Datos privados de estación ✅

(Quick win #2 — campos enriquecidos: RFC, domicilio, permiso CRE, responsables, logos.)

### B1 — Llenar datos privados de una estación

**Quién**: admin.
**Pre-requisitos**: estación creada (Pre-0.3).

**Pasos**:
1. `POST /api/profile` (vía Postman si no hay UI todavía):
   - form-data:
     - `station_id`: 1 (o el ID de tu estación)
     - `rfc`: SES220315ABC
     - `domicilio`: Carretera 145 km 12, Ver.
     - `permiso_cre`: PL/12345/EXP/ES/2026
     - `representante_legal`: Lic. María López
     - `responsable_sasisopa`: Juan Pérez
     - `telefono`: 921-555-0000

**Resultado esperado**: 200 OK con `{"ok": true}`. La fila se actualiza en `station_profiles`.

### B2 — Subir logo de estación

**Quién**: admin.

**Pasos**:
1. `POST /api/profile` con archivo en `logo_estacion`.

**Resultado esperado**: el archivo queda en `uploads/stations/<id>/branding/`. La columna `logo_estacion_path` se actualiza.

### B3 — Verificar que datos privados aparecen en autollenado de plantilla

**Pre-requisitos**: B1 + B2 ejecutados, plantilla del bloque C subida.

**Pasos**:
1. Generar un documento desde la plantilla DOCX (bloque C7).
2. Abrir el `.docx` resultado.

**Resultado esperado**: las variables `<<RFC>>`, `<<DOMICILIO>>`, `<<PERMISO_CRE>>`, etc. salen reemplazadas con los datos de B1.

### B4 — Negativo: usuario no-admin no puede editar datos privados

**Quién**: jefe_test.

**Pasos**:
1. Login como `jefe_test`.
2. Intentar `POST /api/profile`.

**Resultado esperado**: 403 Forbidden.

---

## Bloque C · Plantillas DOCX nuevas ⚠️ (sin UI todavía)

> El motor está implementado y probado, pero la UI de admin para subir/configurar/generar plantillas DOCX **no existe aún**. Mientras tanto, las pruebas se hacen con el script `scripts/demo_docx.py` o vía Postman contra los endpoints `/admin/docx/*`.

### C1 — Smoke test del motor (sin tocar BD real)

**Pasos**:
1. En CMD, en la raíz del proyecto:
   ```
   .venv\Scripts\python.exe scripts\smoke_docx_engine.py
   ```

**Resultado esperado**: imprime "ALL PASS" con 38 verificaciones OK.

### C2 — Smoke test de rutas (test_client interno)

**Pasos**:
1. ```
   .venv\Scripts\python.exe scripts\smoke_docx_routes.py
   ```

**Resultado esperado**: imprime "ALL PASS" con 47 verificaciones. Cubre login, upload, parse, edit fields, publish, generate, list, download, approve, cancel, transición inválida y nueva versión.

### C3 — Demo end-to-end con archivos reales

**Pasos**:
1. ```
   .venv\Scripts\python.exe scripts\demo_docx.py
   ```
2. Abrir la carpeta `demo_output/` que se crea en la raíz.
3. Abrir cada `.docx` en Word:
   - `01_template_master.docx` — plantilla con `<<VARIABLES>>` visibles.
   - `02_doc_aprobado.docx` — variables reemplazadas con datos reales.
   - `03_doc_borrador.docx` — otro generado en estado borrador.

**Resultado esperado**: en `02` y `03`:
- `<<NOMBRE_ESTACION>>` aparece como "Estacion Las Choapas".
- `<<RFC>>` aparece como "SES220315ABC".
- `<<PERMISO_CRE>>` aparece como "PL/12345/EXP/ES/2025".
- `<<FECHA_HOY>>` con la fecha de hoy.
- Las observaciones / hallazgos / medidas correctivas son las que se escribieron al generar.

### C4 — Subir plantilla desde Postman

**Quién**: admin.
**Pre-requisitos**: tener un `.docx` con placeholders `<<RFC>>`, `<<NOMBRE_ESTACION>>`, etc.

**Pasos**:
1. Login (POST `/api/auth/login`).
2. `POST /admin/docx/templates` (multipart):
   - `file`: tu archivo `.docx`
   - `code`: bitacora_test
   - `name`: Bitácora de prueba
   - `module`: sasisopa
   - `description`: prueba manual

**Resultado esperado**: 200 con `template_id`, `version_id="v1.0"`, lista de `fields` con su clasificación (auto/manual/image/date_today).

### C5 — Subir plantilla con código duplicado → rechazo

**Pasos**:
1. Repetir C4 con el mismo `code`.

**Resultado esperado**: 409 Conflict con mensaje *"Ya existe una plantilla con code='…'"*.

### C6 — Editar configuración de un campo

**Pasos**:
1. `POST /admin/docx/templates/<id>/fields` con JSON:
   ```json
   {"fields": [{"id": <field_id>, "label": "Observaciones del día", "is_required": true}]}
   ```

**Resultado esperado**: 200 con `updated >= 1`.

### C7 — Generar documento

**Pasos**:
1. `POST /admin/docx/generate`:
   ```json
   {
     "template_id": <id>,
     "station_id": <station_id>,
     "manual_values": {"OBSERVACIONES": "Sin novedad", "HALLAZGOS": "Ninguno"}
   }
   ```

**Resultado esperado**: 200 con `generated.id`, `status="borrador"`, `docx_path` poblado.

### C8 — Descargar el .docx generado

**Pasos**:
1. `GET /admin/docx/generated/<gen_id>/download`

**Resultado esperado**: descarga un `.docx` que abre en Word con las variables reemplazadas.

### C9 — Aprobar documento

**Pasos**:
1. `POST /admin/docx/generated/<gen_id>/approve`

**Resultado esperado**: 200 con `status="aprobado"`. El registro queda en `audit_log` con action `docx_generated_aprobado`.

### C10 — Cancelar documento + intentar cancelar de nuevo

**Pasos**:
1. Crear nuevo doc (C7).
2. `POST /admin/docx/generated/<gen_id>/cancel` con `{"reason":"Datos incorrectos"}`.
3. Intentar cancelarlo OTRA vez.

**Resultado esperado**: primer cancel → 200, status `cancelado`. Segundo intento → 400 con error `invalid_transition` (estado terminal).

### C11 — Subir nueva versión de plantilla y verificar carry-over

**Pasos**:
1. `POST /admin/docx/templates/<id>/versions` con un `.docx` actualizado.
2. `GET /admin/docx/templates/<id>/fields`.

**Resultado esperado**: nueva versión es `v1.1`. Las variables que ya existían en `v1.0` mantienen el `label` y `is_required` que se configuraron.

---

## Bloque D · Plantillas PDF + coordenadas (legacy SASISOPA / SGM) ✅

(El sistema legado de plantillas con captura por coordenadas. Diferente del motor DOCX nuevo.)

### D1 — Subir plantilla PDF SASISOPA

**Quién**: admin.

**Pasos**:
1. Ir a `Admin → SASISOPA → Plantillas`.
2. Subir un PDF de plantilla.

**Resultado esperado**: aparece en la lista con su mes_key. Se generan previews PNG por página.

### D2 — Definir campos por coordenadas

**Pasos**:
1. Click "Editar campos" en la plantilla recién subida.
2. Añadir 2-3 campos con sus coordenadas (x, y, w, h).
3. Marcar al menos uno como `staff_editable: true`.
4. Guardar schema.

**Resultado esperado**: el JSON de `field_schema_json` queda guardado.

### D3 — Captura admin guarda registro por estación

**Pasos**:
1. Click "Capturar registro" en la plantilla.
2. Seleccionar estación.
3. Llenar campos.
4. Guardar.

**Resultado esperado**: PDF generado con el texto sobre las coordenadas. Registro en `doc_records` único por (brand, module, station_id).

### D4 — Vista jefe de estación ve solo su PDF

**Quién**: jefe_test.

**Pasos**:
1. Login como jefe_test.
2. Ir a `/staff/sasisopa/docs/records`.

**Resultado esperado**: solo aparece el documento de SU estación. No ve los de otras.

### D5 — Jefe puede editar campos staff_editable (si existen)

**Pasos**:
1. En el record que ve, click "Editar".

**Resultado esperado**: solo aparecen los campos marcados como `staff_editable`. Los demás están bloqueados.

---

## Bloque E · Vencimientos y alertas ✅ (cap. 3.3)

(Quick win #1: aviso a 60 días ya activo. Defaults: `60,30,15,7,3,1,0`.)

### E1 — Crear normativa con fecha próxima

**Quién**: admin.
**Pre-requisitos**: estación petroleum creada.

**Pasos**:
1. Ir a `/petroleum/normativas`.
2. Click "Guardar normativa":
   - Estación: tu estación petroleum.
   - Norma: NOM-005 inspección anual.
   - Próxima fecha: dentro de 25 días.
3. Guardar.

**Resultado esperado**: aparece en la tabla con badge "Próximo a vencer" (entre 16 y 30 días → urgencia "proximo").

### E2 — Verificar dashboard de deadlines

**Pasos**:
1. Ir a `/admin/document-deadlines`.

**Resultado esperado**: la normativa de E1 aparece. KPI "Próximos" suma 1.

### E3 — Filtrar por urgencia

**Pasos**:
1. En el dashboard, seleccionar urgencia "16-30 días".
2. Click Actualizar.

**Resultado esperado**: solo aparecen documentos en ese rango.

### E4 — Renovar documento

**Pasos**:
1. En la fila de la normativa, click "Renovar".
2. Capturar nueva fecha (ej. dentro de 1 año).

**Resultado esperado**: la fecha de vencimiento se actualiza. Aparece entrada en `document_renewal_history` con old/new dates.

### E5 — Verificar notificación a 60 días (defalut nuevo)

**Pasos**:
1. Crear normativa con fecha exactamente +60 días.
2. Ejecutar manualmente el scheduler: `POST /api/internal/run-due-tick`.
3. Login como el responsable de la normativa.
4. Ver bandeja de notificaciones.

**Resultado esperado**: notificación tipo "renewal" con texto "Vence en 60 día(s)".

### E6 — Export CSV de deadlines

**Pasos**:
1. Click "Exportar CSV" en `/admin/document-deadlines`.

**Resultado esperado**: descarga `.csv` con todas las filas filtradas.

### E7 — Calendario de renovaciones

**Pasos**:
1. Ir a `/mod/document-renewals-calendar`.

**Resultado esperado**: vista calendario con eventos de renovación.

---

## Bloque F · Expedientes ⚠️ (sin export ZIP — cap. 4)

### F1 — Crear plantilla de expediente

**Quién**: admin.

**Pasos**:
1. Ir a `/admin/expedientes`.
2. Sección "Plantillas obligatorias", llenar:
   - Código: `acta_constitutiva`
   - Título: "Acta constitutiva"
   - Días de vigencia: 0 (sin vigencia)
   - Obligatorio: ✓
3. Click "Guardar plantilla".

**Resultado esperado**: la plantilla aparece en el catálogo.

### F2 — Abrir expediente por estación

**Pasos**:
1. En la misma página, seleccionar una estación.
2. Click "Abrir expediente".

**Resultado esperado**: aparece la lista de documentos obligatorios. La que F1 creó está como `faltante`.

### F3 — Llenar documento del expediente + subir archivo

**Pasos**:
1. En la fila del documento, llenar fecha emisión, fecha vigencia, status `vigente`, notas.
2. Click "Guardar".
3. Click "Adjuntar" y subir un PDF.

**Resultado esperado**: status cambia a `vigente`. KPI "Vigentes" suma 1. El archivo aparece como "Ver archivo".

### F4 — Subir nueva versión del archivo

**Pasos**:
1. En el mismo documento, click "Adjuntar" otra vez con un PDF diferente.

**Resultado esperado**: la columna "Versiones" pasa de 1 a 2.

### F5 — Ver historial de versiones

**Pasos**:
1. Click "Versiones".

**Resultado esperado**: alert/modal con `V1`, `V2`, fechas y URLs de cada archivo.

### F6 — Agregar documento extra (no obligatorio)

**Pasos**:
1. Click "Agregar documento extra".
2. Capturar nombre.

**Resultado esperado**: aparece como fila opcional, status `faltante`.

### F7 — KPIs de expediente

**Pasos**:
1. Llenar varios documentos con distintos estatus (faltante, vigente, vencido, próximo).

**Resultado esperado**: los 4 KPIs (Vigentes / Próx vencer / Vencidos / Obligatorios faltantes) reflejan los conteos correctos.

### F8 — Expediente por cliente libre (sin estación)

**Pasos**:
1. En vez de seleccionar estación, capturar nombre de cliente.
2. Abrir expediente.

**Resultado esperado**: el expediente trabaja sobre el `owner_name` en lugar de estación.

> ⚠️ **NO probar todavía**: el botón "Exportar expediente en ZIP" (cap. 4) **no existe**. La propuesta lo lista como obligatorio pero está pendiente de implementar.

---

## Bloque G · Trámites y normativas ✅

### G1 — Crear trámite

**Quién**: admin.

**Pasos**:
1. Ir a `/admin/tramites`.
2. Llenar formulario: tipo de trámite, asunto, dependencia, fecha límite.
3. Guardar.

**Resultado esperado**: aparece en la tabla con folio autogenerado tipo `TRA-YYYYMMDD-NNNNNN`.

### G2 — Cambiar estatus de trámite

**Pasos**:
1. En la fila, cambiar estatus a "en_proceso".
2. Click guardar.

**Resultado esperado**: actualiza. Audit log registra `update_tramite`.

### G3 — Adjuntar archivo a trámite

**Pasos**:
1. Click "Adjuntar".
2. Subir PDF.

**Resultado esperado**: archivo guardado en `tramites/<id>/`.

### G4 — Crear normativa Petroleum

(Misma sección que E1, no repetir si ya se hizo.)

### G5 — Subir evidencia a normativa

**Pasos**:
1. En la fila de normativa, seleccionar archivo en columna "Evidencia".
2. Click "Evidencia".

**Resultado esperado**: archivo guardado, columna se actualiza.

### G6 — Catálogo base de normativas (admin only)

**Pasos**:
1. En `/petroleum/normativas`, sección "Catálogo base" (solo visible para admin).
2. Crear nueva entrada.

**Resultado esperado**: la nueva normativa base aparece en el dropdown "Catálogo base" al crear una normativa nueva.

---

## Bloque H · Petroleum: control de vigencias ✅ (cap. 7)

### H1 — Crear responsable / dueño

**Quién**: admin (en marca petroleum).

**Pasos**:
1. Ir a `/petroleum/normativas-control` (o `/petroleum/control_vigencias`).
2. Sección "Responsables", llenar nombre, clave corta, color, tel, email.
3. Guardar.

**Resultado esperado**: aparece en lista de responsables con color asignado.

### H2 — Asignar responsable a estación

**Pasos**:
1. En la tabla "Asignación por estación", elegir el responsable creado en H1.

**Resultado esperado**: asignación guardada. La tabla general usa la clave corta y color.

### H3 — Crear nuevo tipo de documento de control

**Pasos**:
1. Sección "Nuevo documento de control".
2. Código: `permiso_cre`, título: `Permiso CRE`, color, orden.
3. Guardar.

**Resultado esperado**: aparece como chip en la lista de tipos.

### H4 — Capturar control para una estación

**Pasos**:
1. Sección "Captura / actualización de control":
   - Estación, tipo de doc, fecha de inicio, fecha de renovación.
   - Estatus documental: vigente.
   - Estatus de pago: pagado, último pago.
2. Guardar.

**Resultado esperado**: aparece en la tabla general con semáforo correcto según fecha de renovación.

### H5 — Filtros de la tabla general

**Pasos**:
1. Probar cada filtro: responsable, estación, tipo de doc, renovación, pago.

**Resultado esperado**: tabla se filtra correctamente.

### H6 — Permisos: jefe NO ve control de vigencias

**Quién**: jefe_pet.

**Pasos**:
1. Login como jefe_pet.
2. Intentar acceder a `/petroleum/normativas-control`.

**Resultado esperado**: redirige o 403. Esa pantalla es admin-only.

---

## Bloque I · Permisos y aislamiento ✅

### I1 — Jefe solo ve su estación

**Quién**: jefe_test.
**Pre-requisitos**: hay 2+ estaciones consulting.

**Pasos**:
1. Login como jefe_test.
2. Ir a `/api/stations`.

**Resultado esperado**: solo aparece la estación a la que está asignado el jefe.

### I2 — Operador solo ve su estación en bitácoras

**Quién**: operador_test.

**Pasos**:
1. Login.
2. `GET /api/bitacoras`.

**Resultado esperado**: solo bitácoras de su estación.

### I3 — Auditor lee pero no escribe

**Quién**: auditor_test.

**Pasos**:
1. `GET /api/normativas` → debe responder.
2. `POST /api/normativas` → debe responder 403.

**Resultado esperado**: lecturas OK, escrituras prohibidas.

### I4 — Brand isolation (consulting no ve petroleum)

**Pasos**:
1. Login como `jefe_test` (consulting only).
2. Intentar abrir `/petroleum/normativas`.

**Resultado esperado**: redirige o 403 si `petroleum` no está en `allowed_brands`.

### I5 — CSRF protection

**Pasos**:
1. Hacer POST a cualquier endpoint sin enviar token CSRF.

**Resultado esperado**: 403 con error "CSRF token inválido o faltante".

> Nota: la UI inyecta el token automáticamente. Esto solo aplica a pruebas vía curl/Postman.

---

## Bloque J · Backups ✅

### J1 — Backup manual

**Pasos**:
1. `Admin → Backups → Crear backup`.

**Resultado esperado**: archivo `backup_YYYYMMDD_HHMMSS.zip` en `backups/`. Fila en `backup_logs` con `kind='manual'`, `triggered_by=<tu user_id>`, `success=1`.

### J2 — Listar backups

**Pasos**:
1. `GET /api/admin/backups`.

**Resultado esperado**: lista con todos los zips, su tamaño y fecha.

### J3 — Backup automático diario

**Pasos**:
1. Esperar 24h o forzar una llamada al scheduler:
   `POST /api/internal/run-due-tick`.

**Resultado esperado**: nueva entrada en `backup_logs` con `kind='scheduled'`, `notes='daily auto backup'`.

### J4 — Verificar retention (máximo 7 backups)

**Pasos**:
1. Crear más de 7 backups manuales en sucesión.

**Resultado esperado**: solo se conservan los 7 más recientes; los más viejos se borran del filesystem.

### J5 — Restore (NO ejecutar en BD real, solo verificar UI)

**Pasos**:
1. Ir a `Admin → Backups → Restaurar`.
2. Seleccionar un zip.
3. Verificar que pide la palabra "RESTAURAR" como confirmación.

**Resultado esperado**: si NO escribes "RESTAURAR" exacto, no procede. (No completar la restauración en la BD real — solo verificar que la confirmación funciona.)

---

## Bloque K · Audit log ✅

### K1 — Ver audit log

**Quién**: admin.

**Pasos**:
1. Ir a `/admin/audit`.

**Resultado esperado**: tabla con las últimas 200 acciones (login, create_user, update_normativa, etc.).

### K2 — Filtrar por usuario

**Pasos**:
1. Buscar por username de un usuario que haya hecho cambios.

**Resultado esperado**: solo aparecen acciones de ese usuario.

### K3 — Filtrar por fechas

**Pasos**:
1. Aplicar rango de fecha.

**Resultado esperado**: tabla recortada al rango.

### K4 — Export audit a CSV

**Pasos**:
1. `GET /api/audit/export.csv`.

**Resultado esperado**: descarga con todas las filas filtradas.

### K5 — Verificar que cada acción importante deja huella

**Pasos**:
1. Hacer una acción (ej. crear normativa).
2. Inmediatamente ir a audit log.

**Resultado esperado**: la acción aparece con timestamp, usuario, módulo, entity_id y detalles JSON.

---

## Bloque L · Bitácoras programadas ❌ NO PROBAR

> **Esta funcionalidad NO está implementada todavía.** La tabla `bitacoras` existe pero solo soporta CRUD básico. No hay vínculo con calendario, no hay plantilla obligatoria, no hay hora límite, no hay estado "vencida si no se llenó".
>
> La propuesta cap. 8 lo lista como obligatorio. Está pendiente para una próxima iteración.

**Cuando se implemente, los escenarios serán:**

- L1: Admin configura actividad de calendario con plantilla y hora límite.
- L2: Estación llena la bitácora antes de la hora límite → status "completada".
- L3: Estación NO llena antes de la hora límite → status "vencida" + notificación a operador, jefe, admin.
- L4: Generar bitácora mensual consolidada.

---

## Bloque M · Export ZIP del expediente ❌ NO PROBAR

> **Esta funcionalidad NO está implementada todavía.** La propuesta cap. 4 lo pide como obligatorio (Reporte_Ejecutivo.pdf + Documentos_Vigentes/ + Vencidos/ + Evidencias/ + Historial.xlsx + Bitácoras/). No existe el botón ni el endpoint.

**Cuando se implemente, los escenarios serán:**

- M1: Click "Exportar ZIP" → descarga zip con la estructura completa.
- M2: Verificar que Reporte_Ejecutivo.pdf incluye resumen de vencimientos.
- M3: Verificar que Historial.xlsx contiene aprobaciones y descargas.

---

## Plantilla para reportar hallazgos

Al terminar las pruebas, llenar para cada bloque:

```
BLOQUE: A
ESCENARIO: A3
RESULTADO: ✅ APROBADO / ❌ FALLADO / ⚠️ COMPORTAMIENTO INESPERADO
NOTAS: <descripción del problema o confirmación>
ARCHIVOS ADJUNTOS: <screenshots, logs, etc.>
USUARIO QUE PROBÓ: <admin / jefe_test / etc.>
FECHA: 2026-MM-DD HH:MM
```

Ejemplo:

```
BLOQUE: E
ESCENARIO: E5
RESULTADO: ⚠️ COMPORTAMIENTO INESPERADO
NOTAS: La notificación a 60 días llegó pero el texto dice "Vence en 60 día(s)" — verificar pluralización.
ARCHIVOS: screenshot_e5.png
USUARIO: admin
FECHA: 2026-05-09 11:30
```

---

## Limpieza después de las pruebas

1. **Borrar usuarios de prueba** creados en Pre-0.2:
   - jefe_test, jefe_pet, operador_test, auditor_test
2. **Borrar estaciones de prueba** si se crearon como demo:
   - C-DEMO-N, P-DEMO
3. **Borrar plantillas DOCX de prueba**: revisar `docx_templates` y eliminar las que tengan code con prefijo `bitacora_test`, `_smoke_`, etc.
4. **Borrar archivos generados de prueba** en:
   - `uploads/docx_templates/`
   - `uploads/docx_generated/`
   - `demo_output/` (carpeta del script demo)
5. **Verificar audit log** para confirmar que todas las acciones quedaron registradas (esto NO se borra; es histórico).

> Si algo se rompe, restaurar el backup creado en Pre-0.1.

---

## Resumen ejecutivo de cobertura

| Capítulo de la propuesta | Cobertura de pruebas |
|---|---|
| Cap. 3 — Control documental | ✅ Bloques D, E, G |
| Cap. 4 — Expediente digital | ⚠️ Bloque F (sin export ZIP) |
| Cap. 5 — Datos privados de estación | ✅ Bloque B |
| Cap. 6 — Plantillas inteligentes DOCX | ⚠️ Bloque C (sin UI, vía script/Postman) |
| Cap. 7 — Petroleum normas/anexos + permisos | ✅ Bloques H, I |
| Cap. 8 — Bitácoras programadas | ❌ Bloque L NO probar |
| Cap. 9 — Aprobaciones e historial | ✅ Bloques C9, K |
| Cap. 10 — Dashboard, semáforos, reportes | ✅ Bloques E, F, H |

**Bloques listos para correr en orden**: Pre-0 → A → B → C → D → E → F → G → H → I → J → K.
**Bloques a saltar**: L, M.

**Tiempo estimado**: 4-6 horas para un solo tester recorriendo todo metódicamente.
