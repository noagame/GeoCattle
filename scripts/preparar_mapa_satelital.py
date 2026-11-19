"""Convierte un GeoTIFF RGB georreferenciado en teselas locales para GeoCattle."""

import argparse
import json
import math
from pathlib import Path

import rasterio
from PIL import Image
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds


WEB_MERCATOR_LIMIT = 20037508.342789244
TILE_SIZE = 256


def tile_ranges(bounds, zoom):
    west, south, east, north = bounds
    count = 1 << zoom
    span = 2 * WEB_MERCATOR_LIMIT / count
    first_x = max(0, math.floor((west + WEB_MERCATOR_LIMIT) / span))
    first_y = max(0, math.floor((WEB_MERCATOR_LIMIT - north) / span))
    last_x = min(count, math.ceil((east + WEB_MERCATOR_LIMIT) / span))
    last_y = min(count, math.ceil((WEB_MERCATOR_LIMIT - south) / span))
    return range(first_x, last_x), range(first_y, last_y), span


def build_tiles(input_file, output, name, attribution, min_zoom, max_zoom):
    with rasterio.open(input_file) as source:
        if not source.crs or source.count < 3 or any(dtype != 'uint8' for dtype in source.dtypes[:3]):
            raise ValueError('El archivo debe ser un GeoTIFF RGB de 8 bits con sistema de coordenadas definido.')
        projected = transform_bounds(source.crs, 'EPSG:3857', *source.bounds)
        west, south, east, north = transform_bounds('EPSG:3857', 'EPSG:4326', *projected)
        if not (-85.05 <= south < north <= 85.05 and -180 <= west < east <= 180):
            raise ValueError('La extensión del GeoTIFF está fuera de Web Mercator o cruza el antimeridiano.')

        output.mkdir(parents=True, exist_ok=False)
        has_alpha = ColorInterp.alpha in source.colorinterp
        count = 0
        for zoom in range(min_zoom, max_zoom + 1):
            columns, rows, span = tile_ranges(projected, zoom)
            for x in columns:
                path = output / str(zoom) / str(x)
                path.mkdir(parents=True)
                left = x * span - WEB_MERCATOR_LIMIT
                for y in rows:
                    top = WEB_MERCATOR_LIMIT - y * span
                    transform = from_bounds(left, top - span, left + span, top, TILE_SIZE, TILE_SIZE)
                    with WarpedVRT(source, crs='EPSG:3857', transform=transform, width=TILE_SIZE,
                                   height=TILE_SIZE, add_alpha=not has_alpha, resampling=Resampling.bilinear) as tile:
                        alpha = tile.colorinterp.index(ColorInterp.alpha) + 1
                        pixels = tile.read([1, 2, 3, alpha]).transpose(1, 2, 0)
                    Image.fromarray(pixels).save(path / f'{y}.webp', quality=86, method=4)
                    count += 1

    manifest = {'name': name, 'attribution': attribution, 'bounds': [south, west, north, east],
                'minZoom': min_zoom, 'maxZoom': max_zoom}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False) + '\n', encoding='utf-8')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geotiff', type=Path)
    parser.add_argument('salida', type=Path, help='Directorio nuevo para las teselas y el manifiesto')
    parser.add_argument('--nombre', required=True)
    parser.add_argument('--atribucion', required=True)
    parser.add_argument('--min-zoom', type=int, default=10)
    parser.add_argument('--max-zoom', type=int, default=14)
    args = parser.parse_args()
    if not 0 <= args.min_zoom <= args.max_zoom <= 20:
        parser.error('Se requiere 0 <= min-zoom <= max-zoom <= 20.')
    print(f'{build_tiles(args.geotiff, args.salida, args.nombre, args.atribucion, args.min_zoom, args.max_zoom)} teselas generadas.')


if __name__ == '__main__':
    main()
