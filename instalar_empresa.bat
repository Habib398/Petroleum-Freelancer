@echo off
setlocal
cd /d %~dp0
if not exist ".venv" (
  echo [1/4] Creando entorno virtual...
  python -m venv .venv
)
call .venv\Scripts\activate

echo [2/4] Actualizando pip...
python -m pip install --upgrade pip

echo [3/4] Instalando dependencias...
pip install -r requirements.txt

echo [4/4] Verificando instalacion...
python -c "import flask, waitress, reportlab, openpyxl, fitz, PIL; print('[OK] Todas las dependencias instaladas correctamente.')"

echo.
echo Instalacion completada.
echo Ejecuta iniciar_empresa.bat para levantar el servidor.
echo Ejecuta DEMO_iniciar.bat para abrir el tunel publico (Cloudflare).
pause
