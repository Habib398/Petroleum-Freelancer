# Cambios realizados para versión de red / AWS

## Hecho en esta entrega
- Se agregó `services/storage.py` para manejar almacenamiento `local` o `s3`.
- Los uploads centrales ahora pasan por la capa de storage.
- Las descargas `/uploads/<path>` ahora funcionan con local o S3.
- Se adaptaron módulos clave para guardar/leer archivos desde storage:
  - uploads
  - advanced (firmas dibujadas)
  - compliance / normativas petroleum
  - documental docs
  - orgchart
- Se añadieron dependencias `boto3` y `psycopg[binary]`.
- Se integró compatibilidad de runtime para PostgreSQL en `db.py` mediante `services/db_compat.py`.
- Se añadieron conversiones para consultas SQLite comunes:
  - `?` → `%s`
  - `INSERT OR IGNORE`
  - `PRAGMA table_info(...)`
  - `sqlite_master`
  - `strftime(...)`
  - `printf('%06d', ...)`
  - `last_insert_rowid()`
- Se actualizó `docker-compose.production.yml` con servicio PostgreSQL para entorno controlado.
- Se actualizó `deploy/aws/env.production.example` para producción con PostgreSQL / RDS.
- Se añadió `scripts/migrate_sqlite_to_postgres.py` para migrar datos desde la base SQLite actual.
- Se actualizó `deploy/aws/DEPLOY_AWS_WORKLOG.md` con flujo real de despliegue y migración.

## Importante
Esta entrega ya no se queda solo en SQLite local: **deja preparada la ruta real a PostgreSQL/RDS**.

Lo que sí sería engañoso afirmar es que quedó 100% certificado en todos los módulos sin probarse en un PostgreSQL real con tu cuenta de AWS. La compatibilidad quedó implementada, pero la validación final debe hacerse con pruebas funcionales del sistema en el entorno destino.

## Recomendación real
- Hoy: EC2 o ECS + RDS PostgreSQL + S3.
- Antes de publicar definitivo: probar login, CRUD, uploads, reportes y notificaciones contra PostgreSQL.
