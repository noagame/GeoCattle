"""Aplicacion y frontend compilado en un mismo origen, solo para inicio local."""
import mimetypes
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from .main import app

app.state.native_local_app = True
mimetypes.add_type('image/webp', '.webp')

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


class SatelliteFiles(StaticFiles):
    async def check_config(self) -> None:
        # La instalación puede operar con la cuadrícula antes de generar las teselas.
        if self.directory is not None and Path(self.directory).exists():
            await super().check_config()


root = Path(__file__).resolve().parents[2]
frontend = root / 'frontend' / 'dist'
app.mount(
    '/mapa-local/satelite',
    SatelliteFiles(directory=root / '.runtime' / 'mapa-satelital', check_dir=False),
    name='satellite',
)
app.mount(
    '/mapa-local/osm',
    SatelliteFiles(directory=root / '.runtime' / 'mapa-osm', check_dir=False),
    name='osm-local',
)
app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
