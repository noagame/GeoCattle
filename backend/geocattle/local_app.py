"""Aplicacion y frontend compilado en un mismo origen, solo para inicio local."""
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .main import app

app.state.native_local_app = True

WEB_CONTENT_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


@app.middleware('http')
async def native_web_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "frame-ancestors 'none'" if request.url.path.startswith('/api/') else WEB_CONTENT_POLICY
    )
    return response


frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
