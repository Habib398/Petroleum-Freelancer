# Work Log general en AWS

## Estado de esta versión
Esta versión queda preparada para una publicación **más profesional** usando:
- Contenedor Docker
- PostgreSQL para producción (RDS recomendado)
- Almacenamiento local o S3 para archivos
- Reverse proxy con Nginx o Application Load Balancer
- Backups a S3
- Script de migración desde la base SQLite actual

## Arquitectura recomendada hoy
1. EC2 o ECS/Fargate para la app
2. Amazon RDS PostgreSQL para la base de datos
3. S3 para archivos y respaldos
4. Nginx o ALB delante de la app
5. Certificado SSL con ACM
6. CloudWatch para logs y monitoreo

## Variables clave de producción
Usa `deploy/aws/env.production.example` como base.

Las más importantes para PostgreSQL son:
```env
COG_DB_ENGINE=postgres
COG_DATABASE_URL=postgresql://usuario:password@host-rds:5432/worklog
COG_STORAGE_MODE=s3
AWS_REGION=us-east-1
COG_S3_BUCKET=tu-bucket
COG_S3_PREFIX=worklog
```

## Flujo recomendado de despliegue
1. Crea la base PostgreSQL en RDS.
2. Crea el bucket S3.
3. Copia el proyecto al servidor.
4. Copia `deploy/aws/env.production.example` a `.env` y ajusta secretos.
5. Construye y levanta la app:
   ```bash
   docker compose -f docker-compose.production.yml up -d --build
   ```
6. Inicializa el esquema en PostgreSQL arrancando la app una vez o ejecutando `python -c "import db; db.init_db()"`.
7. Migra la base SQLite actual si quieres conservar datos:
   ```bash
   export COG_DB_ENGINE=postgres
   export COG_DATABASE_URL=postgresql://usuario:password@host-rds:5432/worklog
   python scripts/migrate_sqlite_to_postgres.py --sqlite data/cog_work_log.db
   ```
8. Configura Nginx o ALB.
9. Configura backups con `deploy/aws/backup_to_s3.sh`.

## Docker Compose incluido
El `docker-compose.production.yml` ya trae:
- un servicio `worklog`
- un servicio `postgres` para pruebas o despliegues simples

Para AWS serio, lo ideal es **reemplazar el postgres del compose por RDS** y dejar solo el contenedor de la app.

## Nota importante
La compatibilidad PostgreSQL se dejó integrada en la capa de base de datos y en consultas problemáticas comunes de SQLite.

Aun así, como esta migración es grande, lo responsable es esto:
- usar esta versión para el salto a PostgreSQL/RDS
- probar login, usuarios, estaciones, documentos, reportes y notificaciones en tu entorno antes de producción final

## Qué revisar antes de publicar
- login y sesiones
- CRUD de usuarios y estaciones
- uploads / descargas
- documentos y evidencias
- reportes PDF y Excel
- notificaciones
- respaldos
- permisos por rol
