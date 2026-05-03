import os
from waitress import serve
from app import create_app

app = create_app()
host = os.environ.get("HOST", "127.0.0.1")
port = int(os.environ.get("PORT", "5000"))
threads = int(os.environ.get("COG_WAITRESS_THREADS", "8"))
serve(app, host=host, port=port, threads=threads)
