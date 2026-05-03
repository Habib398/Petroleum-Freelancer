# COG WORK LOG — Paquete listo para empresa

## Inicio rapido en Windows
1. Descomprime el ZIP en una ruta simple, por ejemplo `C:\COG_WORK_LOG`.
2. Ejecuta `instalar_empresa.bat`.
3. Revisa el archivo `.env`.
4. Ejecuta `iniciar_empresa.bat`.
5. Abre `http://127.0.0.1:5000/inicio` o la URL que configures en `.env`.

## Archivos importantes
- `iniciar_empresa.bat`: arranque seguro con Waitress.
- `iniciar_local_debug.bat`: arranque local en modo debug.
- `respaldo_manual.bat`: genera un ZIP con base de datos, uploads y `.env`.
- `verificar_proyecto.py`: validacion rapida de estructura y sintaxis.
- `.env`: configuracion activa del sistema.
- `.env.example`: plantilla para nueva configuracion.

## Acceso inicial
El usuario administrador inicial se crea solo si no existe otro admin en la base de datos.
Los valores se toman de `.env`:
- `COG_ADMIN_USER`
- `COG_ADMIN_PASS`

## Recomendaciones antes de produccion
- Cambia `COG_SECRET` por una clave nueva si vas a mover el proyecto a otro equipo.
- Cambia la contrasena de admin despues del primer inicio.
- Ejecuta `respaldo_manual.bat` antes de cargar informacion real.
- Usa `APP_DEBUG=0` para operacion normal.

## Componentes del paquete
- Base de datos SQLite existente en `data/cog_work_log.db`.
- Archivos del sistema en `uploads/`.
- Logs rotativos en `logs/app.log`.
- Servidor de produccion local con Waitress.

## Notas
- Si vas a usar HTTPS detras de un proxy, configura `COG_SESSION_SECURE=1`.
- Para red local, cambia `HOST` a `0.0.0.0` en `.env`.
