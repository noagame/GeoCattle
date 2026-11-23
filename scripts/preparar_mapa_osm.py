#!/usr/bin/env python3
"""Genera un mapa OpenStreetMap local (estilo OpenStreetMap Carto) para uso sin Internet.

Flujo: `descargar` baja el extracto de Chile de Geofabrik, `importar` lo carga completo (sin recortar)
en una base PostGIS dentro de Docker y `renderizar` produce teselas PNG en `.runtime/mapa-osm/`,
que la aplicación sirve en `/mapa-local/osm/`. Todo queda fuera de Git.
No usa tile.openstreetmap.org: su política prohíbe la descarga masiva de teselas.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
PBF_DIR = RUNTIME / 'osm'
OUTPUT = RUNTIME / 'mapa-osm'
# Esta compilación usa PostgreSQL 15, igual que geocattle-osm-db existente.
IMAGE = 'overv/openstreetmap-tile-server@sha256:b6a79da39b6d0758368f7c62d22e49dd3ec59e78b194a5ef9dee2723b1f3fa79'
VOLUME = 'geocattle-osm-db'
CONTAINER = 'geocattle-osm-render'
PORT = 18080
GEOFABRIK = 'https://download.geofabrik.de/south-america/chile/chile-{stamp}.osm.pbf'
PBF_NAME = re.compile(r'chile-(?:latest-)?([0-9]{6})\.osm\.pbf')
IMPORTED = PBF_DIR / 'importado.txt'

# (oeste, sur, este, norte)
CHILE = (-75.8, -56.0, -66.3, -17.4)
ARAUCANIA = (-73.65, -39.69, -70.75, -37.50)
TEMUCO = (-72.68, -38.81, -72.44, -38.62)
ATTRIBUTION = '© OpenStreetMap contributors'


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def extract_date(text: str) -> str:
    try:
        if re.fullmatch(r'[0-9]{6}', text):
            datetime.strptime(text, '%y%m%d')
            return text
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('indica una fecha válida en formato AAMMDD')


def local_pbf(stamp: str | None) -> Path:
    candidates = []
    for path in PBF_DIR.glob('chile-*.osm.pbf'):
        match = PBF_NAME.fullmatch(path.name)
        if match and path.is_file() and (not stamp or path.name == f'chile-{stamp}.osm.pbf'):
            info = path.stat()
            if info.st_size > 0:
                candidates.append((match[1], info.st_mtime, path))
    if not candidates:
        sys.exit('Falta el extracto de Chile. Ejecuta primero `descargar` con la misma opción `--fecha`.')
    return max(candidates)[2]


def download_date(last_modified: str | None) -> str:
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).strftime('%y%m%d')
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime('%y%m%d')


def download(args: argparse.Namespace) -> None:
    PBF_DIR.mkdir(parents=True, exist_ok=True)
    url = GEOFABRIK.format(stamp=args.fecha or 'latest')
    target = PBF_DIR / f'chile-{args.fecha}.osm.pbf' if args.fecha else None
    if target and target.is_file() and target.stat().st_size:
        print(f'Ya existe {target}')
        return
    print(f'Descargando {url}', flush=True)
    with tempfile.TemporaryDirectory(dir=PBF_DIR) as folder:
        partial = Path(folder) / 'chile.osm.pbf.part'
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    if target is None:
                        stamp = download_date(response.headers.get('Last-Modified'))
                        destination = PBF_DIR / f'chile-latest-{stamp}.osm.pbf'
                    else:
                        destination = target
                    if destination.is_file() and destination.stat().st_size:
                        print(f'Ya existe {destination}')
                        return
                    length = response.headers.get('Content-Length')
                    with partial.open('wb') as stream:
                        shutil.copyfileobj(response, stream)
                    size = partial.stat().st_size
                    if not size or (length is not None and size != int(length)):
                        raise IncompleteRead(b'', int(length or 0) - size)
                partial.replace(destination)
                print(f'Listo: {destination} ({size / 1e6:.0f} MB)')
                return
            except (urllib.error.URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
                permanent = isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429) and error.code < 500
                if attempt == 3 or permanent:
                    raise SystemExit(f'No se pudo descargar {url}: {error}') from error
                print(f'Descarga incompleta ({attempt}/3). Reintentando…', flush=True)
                time.sleep(2 * attempt)


@contextmanager
def osm_container(args: argparse.Namespace, memory: str, cpus: float, options: list[str], action: str):
    with tempfile.TemporaryDirectory() as folder:
        cid_file = Path(folder) / 'contenedor.id'
        try:
            run(['docker', 'create', '--name', CONTAINER, '--cidfile', str(cid_file),
                 '--memory', args.memoria or memory, '--cpus', str(args.cpus or cpus), '--shm-size', '256m',
                 '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
                 '-v', f'{VOLUME}:/data/database', '-e', f'THREADS={args.hilos}', *options, IMAGE, action],
                stdout=subprocess.DEVNULL)
            yield cid_file.read_text(encoding='ascii').strip()
        finally:
            if cid_file.is_file():
                container_id = cid_file.read_text(encoding='ascii').strip()
                if container_id:
                    subprocess.run(['docker', 'stop', container_id], capture_output=True)
                    run(['docker', 'rm', '-f', container_id], stdout=subprocess.DEVNULL)


def import_pbf(args: argparse.Namespace) -> None:
    source = local_pbf(args.fecha)
    if subprocess.run(['docker', 'volume', 'inspect', VOLUME], capture_output=True).returncode == 0:
        sys.exit(f'El volumen {VOLUME} ya existe. La importación requiere un volumen nuevo. '
                 'Consulta docs/MAPA_OSM_LOCAL.md para conservar o liberar la copia existente.')
    run(['docker', 'volume', 'create', VOLUME], stdout=subprocess.DEVNULL)
    options = ['-v', f'{source}:/data/region.osm.pbf:ro', '-e', 'OSM2PGSQL_EXTRA_ARGS=-C 1024']
    with osm_container(args, '5g', 3, options, 'import') as container_id:
        IMPORTED.write_text('', encoding='ascii')
        run(['docker', 'start', '--attach', container_id])
        IMPORTED.write_text(source.name + '\n', encoding='ascii')


def published_source() -> str | None:
    metadata = OUTPUT / 'FUENTE.md'
    if metadata.is_file():
        match = PBF_NAME.search(metadata.read_text(encoding='utf-8'))
        if match:
            return match[0]
    return None


def render_source(stamp: str | None) -> str:
    source = published_source()
    if IMPORTED.is_file():
        imported = IMPORTED.read_text(encoding='ascii').strip()
        if not PBF_NAME.fullmatch(imported):
            sys.exit('La importación anterior quedó incompleta. Repite `importar`.')
        if source and source != imported:
            sys.exit(f'Archiva {OUTPUT} antes de renderizar otro extracto.')
        source = imported
    if source and stamp and source != f'chile-{stamp}.osm.pbf':
        sys.exit(f'El extracto importado es {source}. Ejecuta `importar` para cambiarlo.')
    return source or local_pbf(stamp).name


def tile_x(lon: float, zoom: int) -> int:
    return min(2 ** zoom - 1, max(0, int((lon + 180) / 360 * 2 ** zoom)))


def tile_y(lat: float, zoom: int) -> int:
    radians = math.radians(max(-85.05, min(85.05, lat)))
    value = (1 - math.asinh(math.tan(radians)) / math.pi) / 2 * 2 ** zoom
    return min(2 ** zoom - 1, max(0, int(value)))


def tiles(bounds: tuple[float, float, float, float], zooms: range):
    west, south, east, north = bounds
    for zoom in zooms:
        x0, x1 = tile_x(west, zoom), tile_x(east, zoom)
        y0, y1 = tile_y(north, zoom), tile_y(south, zoom)
        # Agrupa por bloques de 8x8 para aprovechar cada metateselas renderizada.
        coords = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        coords.sort(key=lambda c: (c[0] // 8, c[1] // 8, c[0], c[1]))
        for x, y in coords:
            yield zoom, x, y


def fetch(job: tuple[int, int, int], retries: int = 4) -> bool:
    zoom, x, y = job
    path = OUTPUT / str(zoom) / str(x) / f'{y}.png'
    if path.exists() and path.stat().st_size > 0:
        return False
    url = f'http://127.0.0.1:{PORT}/tile/{zoom}/{x}/{y}.png'
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                data = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix('.tmp').write_bytes(data)
            path.with_suffix('.tmp').replace(path)
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'No se pudo obtener {zoom}/{x}/{y}')


def parse_range(text: str) -> range:
    low, _, high = text.partition('-')
    return range(int(low), int(high or low) + 1)


def render(args: argparse.Namespace) -> None:
    plan = [('Chile completo', CHILE, parse_range(args.chile)),
            ('La Araucanía', ARAUCANIA, parse_range(args.region)),
            ('Entorno de Temuco', TEMUCO, parse_range(args.detalle))]
    jobs: list[tuple[int, int, int]] = []
    for label, bounds, zooms in plan:
        count = sum(1 for _ in tiles(bounds, zooms))
        print(f'{label}: z{zooms.start}–z{zooms.stop - 1}, {count} teselas')
        jobs.extend(tiles(bounds, zooms))
    if args.solo_contar:
        print(f'Total {len(jobs)} teselas')
        return
    if subprocess.run(['docker', 'volume', 'inspect', VOLUME], stdout=subprocess.DEVNULL).returncode:
        sys.exit(f'No se pudo abrir el volumen {VOLUME}. Comprueba Docker y ejecuta `importar` si el volumen falta.')
    with osm_container(args, '2g', 2, ['-p', f'127.0.0.1:{PORT}:80'], 'run') as container_id:
        source = render_source(args.fecha)
        run(['docker', 'start', container_id], stdout=subprocess.DEVNULL)
        for _ in range(120):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/tile/0/0/0.png', timeout=60):
                    pass
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(2)
        else:
            sys.exit('El servidor de teselas no respondió.')
        started, done, new = time.monotonic(), 0, 0
        with ThreadPoolExecutor(max_workers=args.hilos) as pool:
            for created in pool.map(fetch, jobs):
                done += 1
                new += created
                if done % 500 == 0 or done == len(jobs):
                    rate = done / max(1, time.monotonic() - started)
                    print(f'{done}/{len(jobs)} ({rate:.1f}/s)', flush=True)
        write_metadata(source, plan)


def write_metadata(source: str, plan) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    west, south, east, north = CHILE
    manifest = {'name': 'OpenStreetMap local · Chile', 'attribution': ATTRIBUTION,
                'bounds': [south, west, north, east], 'minZoom': 0, 'maxZoom': max(z.stop - 1 for _, _, z in plan),
                'regional': {'bounds': [ARAUCANIA[1], ARAUCANIA[0], ARAUCANIA[3], ARAUCANIA[2]],
                             'minZoom': plan[1][2].start, 'maxZoom': plan[1][2].stop - 1},
                'detail': {'bounds': [TEMUCO[1], TEMUCO[0], TEMUCO[3], TEMUCO[2]],
                           'minZoom': plan[2][2].start, 'maxZoom': plan[2][2].stop - 1}}
    lines = [
        '# Fuente del mapa OpenStreetMap local', '',
        f'- Datos: extracto de Chile de Geofabrik (`{source}`), © OpenStreetMap contributors, '
        'licencia ODbL (https://www.openstreetmap.org/copyright). Se importó completo, sin recortar.',
        '- Estilo: OpenStreetMap Carto (CC BY-SA 2.0), renderizado con Mapnik en la imagen '
        f'`{IMAGE}` (PostgreSQL 15).',
        f'- Generado el {date.today().isoformat()} con `scripts/preparar_mapa_osm.py`.',
        f'- Cobertura de teselas: Chile z{plan[0][2].start}–{plan[0][2].stop - 1}; '
        f'La Araucanía z{plan[1][2].start}–{plan[1][2].stop - 1}; entorno de Temuco '
        f'z{plan[2][2].start}–{plan[2][2].stop - 1}. Fuera de ese detalle, el mapa se amplía desde el último nivel.',
        '- No se descargaron teselas de tile.openstreetmap.org, cuya política prohíbe la descarga masiva.', '',
    ]
    (OUTPUT / 'FUENTE.md').write_text('\n'.join(lines), encoding='utf-8')
    staging = OUTPUT / 'manifest.json.tmp'
    staging.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    staging.replace(OUTPUT / 'manifest.json')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fecha', type=extract_date, help='Extracto fechado de Geofabrik (AAMMDD)')
    parser.add_argument('--hilos', type=int, default=2, help='Hilos de importación y renderizado (2 por defecto)')
    parser.add_argument('--memoria', help='Límite Docker (importación: 5g, renderizado: 2g)')
    parser.add_argument('--cpus', type=float, help='Límite Docker (importación: 3, renderizado: 2)')
    commands = parser.add_subparsers(dest='orden', required=True)
    commands.add_parser('descargar').set_defaults(func=download)
    commands.add_parser('importar').set_defaults(func=import_pbf)
    renderer = commands.add_parser('renderizar')
    renderer.add_argument('--chile', default='0-11', help='Rango de zoom para todo Chile')
    renderer.add_argument('--region', default='12-15', help='Rango de zoom para La Araucanía')
    renderer.add_argument('--detalle', default='16-17', help='Rango de zoom para el entorno de Temuco')
    renderer.add_argument('--solo-contar', action='store_true')
    renderer.set_defaults(func=render)
    args = parser.parse_args()
    if args.hilos < 1 or (args.cpus is not None and (not math.isfinite(args.cpus) or args.cpus <= 0)):
        parser.error('--hilos y --cpus deben ser positivos')
    args.func(args)


if __name__ == '__main__':
    main()
