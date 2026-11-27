# Mapa satelital de La Araucanía

**Contains modified Copernicus Sentinel data 2025**

El mosaico Sentinel-2 de enero a marzo de 2025 combina B04, B03 y B02 en color natural a partir de bandas de 10 m por píxel. El recorte WGS84 va de 73,65° O a 70,75° O y de 39,69° S a 37,50° S. Abarca la extensión de La Araucanía y agrega margen en los cuatro lados. Las zonas sin observaciones válidas dejan visible la cuadrícula. [Límites ADM1 de geoBoundaries, basados en BCN de Chile y OCHA ROLAC](https://www.geoboundaries.org/api/current/gbOpen/CHL/ADM1/).

- La zona UTM 18S aporta `18HXB_0_0`, `18HXC_0_0`, `18HXD_0_0`, `18HYB_0_0`, `18HYC_0_0` y `18HYD_0_0`.
- La zona UTM 19S aporta `19HBS_0_0`, `19HBT_0_0`, `19HBU_0_0`, `19HCS_0_0`, `19HCT_0_0` y `19HCU_0_0`.

El generador reproyecta el mosaico a Web Mercator y aplica los mismos percentiles 2 y 98 por canal y gamma 1,25 a todas las cuadrículas. En los solapes toma el primer píxel válido y completa los huecos con las otras fuentes. Los niveles regionales se reducen por promedio hasta z12 y el detalle usa Lanczos en z13–14. Se guardan teselas XYZ de 256 px en WebP calidad 92. A esta latitud, z14 equivale a unos 7,5 m por píxel en pantalla y es el nivel nativo máximo. Los acercamientos posteriores amplían z14 y permiten inspeccionar las geometrías de GeoCattle.

[Catálogo de mosaicos trimestrales de Sentinel-2](https://source.coop/tge-labs/sentinel-2-quarterly-cloudless-mosaics) · [Aviso legal de Copernicus Sentinel](https://ewds.climate.copernicus.eu/licences/ec-sentinel).

## Instalación y verificación

El PC del campo ofrece este mosaico como **Satélite local**. La web espejo sirve **Satélite en línea** desde Esri World Imagery y omite el manifiesto local. [Mapas del despliegue](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#mapas)

Instala `rasterio` y `Pillow` en un entorno Python aparte y ejecuta el siguiente comando desde la raíz. [Preparar el entorno](../README.md#mapa-local-y-traslado-de-collares)

```bash
python scripts/preparar_mapa_satelital.py --araucania
```

El script lee los COG públicos de Source Cooperative por rangos HTTPS y genera z8–14 en `.runtime/mapa-satelital/`. Para una instalación inicial que descargue menos datos, puedes limitar todos los niveles a z11 con `--max-zoom 11` o generar detalle solo en Temuco con este comando.

```bash
python scripts/preparar_mapa_satelital.py --araucania --zoom-regional 11 --detalle-bbox -72.68 -38.81 -72.44 -38.62
```

Fuera de ese recorte, el mapa amplía la imagen de z11. Si ya cuentas con los COG originales, `--cache-fuentes RUTA` busca cada banda en `RUTA/CUADRÍCULA_0_0/BANDA.tif` y consulta la fuente pública para las bandas faltantes.

El directorio de salida debe estar vacío. Para reemplazar una instalación existente, genera primero en una carpeta temporal con `--directorio-salida`. Guarda aparte el manifiesto anterior y copia el nuevo contenido a `.runtime/mapa-satelital/`. Publica el nuevo `manifest.json` al final. El directorio de destino es el que se monta en Docker. Vite, el inicio nativo de FastAPI y Nginx leen el mismo conjunto en `/mapa-local/satelite/`. El manifiesto mantiene `name`, `attribution`, `bounds` en orden sur, oeste, norte, este, `minZoom` y `maxZoom`. Si hay un recorte de detalle, incluye `detail.bounds` en el mismo orden y `detail.minZoom` con su primer nivel. La copia local de `FUENTE.md` registra los parámetros usados.

En el origen que sirve el paquete local, abre `/mapa-local/satelite/manifest.json` y comprueba que una ruta `/mapa-local/satelite/{z}/{x}/{y}.webp` devuelva `image/webp`. Con el paquete ausente, el manifiesto devuelve 404 y el mapa muestra la cuadrícula WGS84.

## Ortofotos de un predio

Usa archivos RGB georreferenciados con permiso de uso offline. El conversor admite varios GeoTIFF y COG, también por HTTPS. Ordena primero la imagen prioritaria en caso de solape. Puedes acotar la salida con `--bbox OESTE SUR ESTE NORTE` y escoger el nivel máximo según la resolución de la fuente.

```bash
python scripts/preparar_mapa_satelital.py predio-norte.tif predio-sur.tif --directorio-salida .runtime/mapa-satelital --nombre "Ortofoto del predio" --atribucion "Fuente y fecha" --min-zoom 12 --max-zoom 17
```
