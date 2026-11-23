"""Prepara un mosaico satelital local WebP a partir de GeoTIFF RGB o COG Sentinel-2."""

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import ColorInterp, Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds as window_from_bounds


WEB_MERCATOR_LIMIT = 20037508.342789244
TILE_SIZE = 256
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / '.runtime' / 'mapa-satelital'
ARAUCANIA_BOUNDS = (-73.65, -39.69, -70.75, -37.50)
SENTINEL_ROOT = 'https://data.source.coop/tge-labs/sentinel-2-quarterly-cloudless-mosaics/2025/Q1'
SENTINEL_GRIDS = (
    '18HXB', '18HXC', '18HXD', '18HYB', '18HYC', '18HYD',
    '19HBS', '19HBT', '19HBU', '19HCS', '19HCT', '19HCU',
)
SENTINEL_NAME = 'La Araucanía · Sentinel-2 · enero a marzo de 2025'
SENTINEL_ATTRIBUTION = 'Contains modified Copernicus Sentinel data 2025'


def tile_ranges(bounds, zoom):
    west, south, east, north = bounds
    count = 1 << zoom
    span = 2 * WEB_MERCATOR_LIMIT / count
    first_x = max(0, math.floor((west + WEB_MERCATOR_LIMIT) / span))
    first_y = max(0, math.floor((WEB_MERCATOR_LIMIT - north) / span))
    last_x = min(count, math.ceil((east + WEB_MERCATOR_LIMIT) / span))
    last_y = min(count, math.ceil((WEB_MERCATOR_LIMIT - south) / span))
    return range(first_x, last_x), range(first_y, last_y), span


def intersection(a, b):
    left, bottom = max(a[0], b[0]), max(a[1], b[1])
    right, top = min(a[2], b[2]), min(a[3], b[3])
    if left < right and bottom < top:
        return left, bottom, right, top
    return None


def sentinel_source(stack, grid, overview, cache):
    paths = []
    for band in ('B04', 'B03', 'B02'):
        relative = f'{grid}_0_0/{band}.tif'
        local = cache / relative if cache else None
        paths.append(local.resolve().as_posix() if local and local.is_file()
                     else f'/vsicurl/{SENTINEL_ROOT}/{relative}')

    options = {} if overview is None else {'overview_level': overview}
    with rasterio.open(paths[0], **options) as red:
        width, height = red.width, red.height
        geotransform = ','.join(map(str, red.transform.to_gdal()))
        srs = escape(red.crs.to_wkt())
    # Cada banda se abre en la misma cuadrícula y al mismo nivel del COG.
    overview_option = '' if overview is None else (
        f'<OpenOptions><OOI key="OVERVIEW_LEVEL">{overview}</OOI></OpenOptions>'
    )
    bands = ''.join(
        f'<VRTRasterBand dataType="Int16" band="{index}"><ColorInterp>{color}</ColorInterp>'
        f'<NoDataValue>-32768</NoDataValue><SimpleSource><SourceFilename>{escape(path)}</SourceFilename>'
        f'<SourceBand>1</SourceBand>{overview_option}<SrcRect xOff="0" yOff="0" xSize="{width}" ySize="{height}"/>'
        f'<DstRect xOff="0" yOff="0" xSize="{width}" ySize="{height}"/></SimpleSource></VRTRasterBand>'
        for index, (color, path) in enumerate(zip(('Red', 'Green', 'Blue'), paths), 1)
    )
    vrt = (f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}"><SRS>{srs}</SRS>'
           f'<GeoTransform>{geotransform}</GeoTransform>{bands}</VRTDataset>')
    memory = stack.enter_context(MemoryFile(vrt.encode('utf-8'), ext='.vrt'))
    return stack.enter_context(memory.open())


def open_sources(stack, inputs, overview, cache):
    if not inputs:
        return [sentinel_source(stack, grid, overview, cache) for grid in SENTINEL_GRIDS]
    sources = [stack.enter_context(rasterio.open(path)) for path in inputs]
    for source in sources:
        if not source.crs or source.count < 3 or len(set(source.dtypes[:3])) != 1:
            raise ValueError(f'Se requiere un GeoTIFF georreferenciado con tres bandas RGB: {source.name}')
    return sources


def color_range(sources, wgs84_bounds):
    samples = []
    for source in sources:
        area = intersection(source.bounds, transform_bounds('EPSG:4326', source.crs, *wgs84_bounds))
        if area is None:
            continue
        window = window_from_bounds(*area, transform=source.transform)
        rgb = source.read([1, 2, 3], window=window, out_shape=(3, 128, 128), masked=True)
        valid = ~np.ma.getmaskarray(rgb).any(axis=0) & np.isfinite(rgb.data).all(axis=0)
        samples.append(rgb.data[:, valid])
    if not samples or not any(sample.size for sample in samples):
        raise ValueError('Las fuentes no contienen píxeles válidos en el recorte solicitado.')
    low, high = np.percentile(np.concatenate(samples, axis=1), (2, 98), axis=1)
    high = np.where(high > low, high, low + 1)
    return low[:, None], (high - low)[:, None]


def native_overview(zoom):
    # Q1 incluye pirámides de 2×, 4×, 8×, 16× y 32×. Mantén la nativa desde z13.
    return min(4, 12 - zoom) if zoom <= 12 else None


def aligned_sources(stack, sources, columns, rows, span, zoom):
    left = columns.start * span - WEB_MERCATOR_LIMIT
    top = WEB_MERCATOR_LIMIT - rows.start * span
    right, bottom = left + len(columns) * span, top - len(rows) * span
    transform = from_bounds(left, bottom, right, top, len(columns) * TILE_SIZE, len(rows) * TILE_SIZE)
    resampling = Resampling.average if zoom <= 12 else Resampling.lanczos
    for source in sources:
        footprint = transform_bounds(source.crs, 'EPSG:3857', *source.bounds)
        if intersection(footprint, (left, bottom, right, top)) is None:
            continue
        add_alpha = ColorInterp.alpha not in source.colorinterp
        vrt = stack.enter_context(WarpedVRT(
            source, crs='EPSG:3857', transform=transform, width=len(columns) * TILE_SIZE,
            height=len(rows) * TILE_SIZE, add_alpha=add_alpha, resampling=resampling, tolerance=0.05,
        ))
        yield vrt, footprint, vrt.colorinterp.index(ColorInterp.alpha) + 1


def render_block(aligned, window, projected, stretch, gamma):
    width, height = int(window.width), int(window.height)
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    transform = aligned[0][0].transform
    left, top = transform * (window.col_off, window.row_off)
    right, bottom = transform * (window.col_off + width, window.row_off + height)
    west, south, east, north = projected
    x_centers = left + (np.arange(width) + 0.5) * transform.a
    y_centers = top + (np.arange(height) + 0.5) * transform.e
    remaining = ((y_centers >= south) & (y_centers <= north))[:, None] & (
        (x_centers >= west) & (x_centers <= east)
    )
    low, scale = stretch
    for vrt, footprint, alpha in aligned:
        if intersection(footprint, (left, bottom, right, top)) is None:
            continue
        values = vrt.read([1, 2, 3, alpha], window=window)
        valid = remaining & (values[3] > 0) & np.isfinite(values[:3]).all(axis=0)
        normalized = np.clip((values[:3, valid] - low) / scale, 0, 1)
        pixels[valid, :3] = np.rint(normalized.T ** (1 / gamma) * 255).astype(np.uint8)
        pixels[valid, 3] = 255
        remaining[valid] = False
        if not remaining.any():
            break
    return pixels


def save_tile(path, pixels, quality):
    image = Image.fromarray(pixels)
    if image.getextrema()[3] == (255, 255):
        image = image.convert('RGB')
    image.save(path, quality=quality, method=3)


def write_zoom(output, sources, projected, stretch, zoom, gamma, quality, pool):
    columns, rows, span = tile_ranges(projected, zoom)
    level = output / str(zoom)
    for x in columns:
        (level / str(x)).mkdir(parents=True)
    block_size = 4  # Cantidad de teselas contiguas por lectura desde el mosaico.
    with ExitStack() as stack:
        aligned = list(aligned_sources(stack, sources, columns, rows, span, zoom))
        if not aligned:
            raise ValueError('Las fuentes no intersectan el recorte solicitado.')
        for y in range(rows.start, rows.stop, block_size):
            height = min(block_size, rows.stop - y)
            for x in range(columns.start, columns.stop, block_size):
                width = min(block_size, columns.stop - x)
                window = Window((x - columns.start) * TILE_SIZE, (y - rows.start) * TILE_SIZE,
                                width * TILE_SIZE, height * TILE_SIZE)
                pixels = render_block(aligned, window, projected, stretch, gamma)
                jobs = [
                    pool.submit(save_tile, level / str(x + ix) / f'{y + iy}.webp',
                                pixels[iy * TILE_SIZE:(iy + 1) * TILE_SIZE, ix * TILE_SIZE:(ix + 1) * TILE_SIZE],
                                quality)
                    for iy in range(height) for ix in range(width)
                ]
                for job in jobs:
                    job.result()
    return len(columns) * len(rows)


def source_notes(args, bounds):
    details = (
        f'{args.atribucion}\n\n'
        f'Cobertura WGS84 (oeste, sur, este, norte) `{bounds}`. '
        f'Niveles XYZ {args.min_zoom} a {args.max_zoom}, WebP de {TILE_SIZE} px con calidad {args.calidad}. '
        f'Percentiles globales 2 y 98 por canal, gamma {args.gamma}, promedio en z≤12 y Lanczos desde z13.\n'
    )
    if args.detalle_bbox:
        details += (f'\nCobertura regional hasta z{args.zoom_regional}. Desde z{args.zoom_regional + 1}, '
                    f'detalle WGS84 (oeste, sur, este, norte) `{args.detalle_bbox}`.\n')
    if args.araucania:
        details += (
            '\nSentinel-2, enero a marzo de 2025. Bandas B04, B03 y B02 de 10 m por píxel. Cuadrículas '
            + ', '.join(f'`{grid}_0_0`' for grid in SENTINEL_GRIDS) + '.\n\n'
            '- [Mosaicos trimestrales](https://source.coop/tge-labs/sentinel-2-quarterly-cloudless-mosaics).\n'
            '- [Aviso legal de Copernicus Sentinel](https://ewds.climate.copernicus.eu/licences/ec-sentinel).\n'
        )
    return f'# {args.nombre}\n\n{details}'


def build_tiles(args):
    args.salida.mkdir(parents=True, exist_ok=True)
    if any(args.salida.iterdir()):
        raise ValueError(f'La salida debe ser un directorio nuevo o vacío: {args.salida}')
    with ExitStack() as stack:
        sample = open_sources(stack, args.geotiff, 4, args.cache_fuentes)
        bounds = args.bbox
        if bounds is None:
            footprints = [transform_bounds(src.crs, 'EPSG:4326', *src.bounds) for src in sample]
            bounds = (min(b[0] for b in footprints), min(b[1] for b in footprints),
                      max(b[2] for b in footprints), max(b[3] for b in footprints))
        west, south, east, north = bounds
        if not (-85.05 <= south < north <= 85.05 and -180 <= west < east <= 180):
            raise ValueError('El recorte está fuera de Web Mercator, es inválido o cruza el antimeridiano.')
        projected = transform_bounds('EPSG:4326', 'EPSG:3857', *bounds)
        detail = None
        if args.detalle_bbox:
            w, s, e, n = args.detalle_bbox
            if not (west <= w < e <= east and south <= s < n <= north):
                raise ValueError('El recorte de detalle debe quedar dentro de la cobertura regional.')
            detail = transform_bounds('EPSG:4326', 'EPSG:3857', w, s, e, n)
        stretch = color_range(sample, bounds)
        print('Estiramiento RGB (mínimo, amplitud):', *[v.ravel().round(1).tolist() for v in stretch], flush=True)

    with TemporaryDirectory(prefix='.mapa-satelital-', dir=args.salida.parent) as staging, ThreadPoolExecutor(max_workers=6) as pool:
        output = Path(staging)
        previous = object()
        count = 0
        with ExitStack() as sources_stack:
            for zoom in range(args.min_zoom, args.max_zoom + 1):
                overview = None if args.geotiff else native_overview(zoom)
                if overview != previous:
                    sources_stack.close()
                    sources = open_sources(sources_stack, args.geotiff, overview, args.cache_fuentes)
                    previous = overview
                area = detail if detail is not None and zoom > args.zoom_regional else projected
                tiles = write_zoom(output, sources, area, stretch, zoom, args.gamma, args.calidad, pool)
                count += tiles
                print(f'z{zoom}: {tiles} teselas.', flush=True)
        manifest = {'name': args.nombre, 'attribution': args.atribucion, 'bounds': [south, west, north, east],
                    'minZoom': args.min_zoom, 'maxZoom': args.max_zoom}
        if detail is not None:
            manifest['detail'] = {'bounds': [s, w, n, e], 'minZoom': args.zoom_regional + 1}
        (output / 'FUENTE.md').write_text(source_notes(args, bounds), encoding='utf-8')
        if any(args.salida.iterdir()):
            raise ValueError(f'Otro proceso escribió en el directorio de salida: {args.salida}')
        for path in output.iterdir():
            path.rename(args.salida / path.name)
        temporary = output / 'manifest.json'
        temporary.write_text(json.dumps(manifest, ensure_ascii=False) + '\n', encoding='utf-8')
        temporary.rename(args.salida / temporary.name)
        return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geotiff', nargs='*', help='GeoTIFF RGB locales o COG por URL')
    parser.add_argument('--araucania', action='store_true', help='Mosaico regional de Sentinel-2 de 2025/Q1')
    parser.add_argument('--directorio-salida', dest='salida', type=Path, help='Directorio nuevo o vacío')
    parser.add_argument('--cache-fuentes', type=Path, help='COG locales opcionales, en cuadrícula_0_0/banda.tif')
    parser.add_argument('--nombre')
    parser.add_argument('--atribucion')
    bounds_order = ('OESTE', 'SUR', 'ESTE', 'NORTE')
    parser.add_argument('--bbox', nargs=4, type=float, metavar=bounds_order)
    parser.add_argument('--detalle-bbox', nargs=4, type=float, metavar=bounds_order,
                        help='Limita la cobertura desde el nivel siguiente a --zoom-regional')
    parser.add_argument('--zoom-regional', type=int, default=10, help='Último nivel regional si se indica --detalle-bbox')
    parser.add_argument('--min-zoom', type=int)
    parser.add_argument('--max-zoom', type=int, default=14)
    parser.add_argument('--calidad', type=int, default=92)
    parser.add_argument('--gamma', type=float, default=1.25)
    args = parser.parse_args()
    # Conserva la forma posicional GEOTIFF SALIDA del conversor original.
    if not args.araucania and args.salida is None and len(args.geotiff) > 1:
        args.salida = Path(args.geotiff.pop())
    if args.araucania:
        if args.geotiff:
            parser.error('--araucania usa las fuentes públicas del mosaico.')
        args.nombre = args.nombre or SENTINEL_NAME
        args.atribucion = SENTINEL_ATTRIBUTION
        args.bbox = args.bbox or ARAUCANIA_BOUNDS
    elif not (args.geotiff and args.nombre and args.atribucion):
        parser.error('Indica --araucania o GeoTIFF de entrada con --nombre y --atribucion.')
    args.salida = args.salida or DEFAULT_OUTPUT
    if args.min_zoom is None:
        args.min_zoom = 8 if args.araucania else 10
    if not 0 <= args.min_zoom <= args.max_zoom <= 20:
        parser.error('Se requiere 0 <= min-zoom <= max-zoom <= 20.')
    if args.detalle_bbox and not args.min_zoom <= args.zoom_regional < args.max_zoom:
        parser.error('--zoom-regional debe quedar entre min-zoom y max-zoom, sin incluir max-zoom.')
    if not 1 <= args.calidad <= 100 or not math.isfinite(args.gamma) or args.gamma <= 0:
        parser.error('La calidad debe estar entre 1 y 100 y el gamma debe ser positivo.')
    try:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY='3', GDAL_HTTP_RETRY_DELAY='1',
            GDAL_HTTP_TIMEOUT='55', GDAL_HTTP_CONNECTTIMEOUT='15',
        ):
            print(f'{build_tiles(args)} teselas generadas en {args.salida}.')
    except (ValueError, OSError, rasterio.errors.RasterioError) as error:
        parser.exit(1, f'No se pudo preparar el mapa: {error}\n')


if __name__ == '__main__':
    main()
