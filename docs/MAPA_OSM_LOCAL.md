# Mapa OpenStreetMap local

GeoCattle puede mostrar OpenStreetMap sin Internet con el mismo estilo del mapa estándar (OpenStreetMap Carto). Las teselas se generan en el equipo a partir de los datos de OpenStreetMap; no se descargan de `tile.openstreetmap.org`, cuya política prohíbe la descarga masiva.

## Qué incluye

- Datos: extracto completo de Chile de Geofabrik, importado sin recortar. © OpenStreetMap contributors, licencia ODbL.
- Teselas PNG 256 px en `.runtime/mapa-osm/{z}/{x}/{y}.png`, con `manifest.json` y `FUENTE.md`. Quedan fuera de Git.
- Cobertura por defecto: Chile completo z0–11, La Araucanía z12–15 y entorno de Temuco z16–17. Fuera de esas áreas el navegador amplía el último nivel disponible.
- En el PC del campo aparece como **OpenStreetMap local**, junto a **Satélite local** y **OpenStreetMap** en línea. La web espejo usa OpenStreetMap estándar en línea como base inicial. [Mapas del despliegue](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#mapas)

## Instalación

Requiere Docker con contenedores Linux y espacio para el extracto, la base y las teselas. Desde la raíz:

```
python scripts/preparar_mapa_osm.py descargar
python scripts/preparar_mapa_osm.py importar
python scripts/preparar_mapa_osm.py renderizar
```

- `descargar` obtiene `chile-latest.osm.pbf` de Geofabrik (unos 350 MB). Guarda el archivo como `.runtime/osm/chile-latest-AAMMDD.osm.pbf` con la fecha de `Last-Modified` o, si falta, la fecha UTC de descarga. Usa un archivo temporal `.part` y reintenta descargas incompletas hasta tres intentos en total. Para un extracto fechado aún disponible, coloca `--fecha AAMMDD` antes del subcomando.
- `importar` selecciona el extracto local más reciente por la fecha en el nombre. Si se indica `--fecha AAMMDD`, usa el archivo fechado correspondiente. Carga el extracto completo en un volumen nuevo `geocattle-osm-db` y registra el archivo usado en `.runtime/osm/importado.txt`.
- `renderizar` sirve teselas temporalmente en `127.0.0.1:18080`, guarda los PNG y retira su contenedor al terminar. Al repetirlo con el mismo extracto, reutiliza las teselas existentes. Ajusta cobertura con `--chile`, `--region` y `--detalle` (rangos como `12-15`). `--solo-contar` calcula el total sin usar Docker. El `FUENTE.md` generado identifica el extracto y el digest de la imagen.
- La importación tiene un tope de 5 GiB y 3 CPU. El renderizado tiene un tope de 2 GiB y 2 CPU. Ambos usan dos hilos por defecto. Puedes cambiar los topes y los hilos antes del subcomando, por ejemplo `python scripts/preparar_mapa_osm.py --memoria 3g --cpus 2 --hilos 2 renderizar`.

La imagen del tile server se fija por el digest `sha256:b6a79da39b6d0758368f7c62d22e49dd3ec59e78b194a5ef9dee2723b1f3fa79`, que usa PostgreSQL 15 y es compatible con el volumen generado originalmente. La versión etiquetada `2.3.0` usa PostgreSQL 14.

Tras instalar, el servidor ya activo sirve las teselas sin reiniciarse en el inicio nativo. Con Docker Compose, el directorio `.runtime/mapa-osm/` debe existir al levantar `web`.

## Liberar espacio y actualizar

La aplicación lee las teselas desde `.runtime/mapa-osm/`. Verifica que el manifiesto y las teselas estén disponibles y conserva una copia de esa carpeta si planeas regenerarlas. El volumen de importación puede ocupar varios GB (se midieron 15,19 GB para Chile). Si ya terminaste de generar teselas y decides descartar la base auxiliar, administra únicamente ese volumen:

```sh
docker ps -a --filter volume=geocattle-osm-db
docker volume inspect geocattle-osm-db
docker volume rm geocattle-osm-db
```

Ejecuta el último comando solo cuando la primera consulta no muestre contenedores que lo usen. El volumen contiene la base de renderizado y perderlo obliga a repetir la importación si necesitas generar más teselas. Los PNG existentes permanecen disponibles en el anfitrión.

Para actualizar, descarga el nuevo extracto y archiva `.runtime/mapa-osm/` fuera de esa ruta. Cuando hayas liberado el volumen auxiliar de la versión anterior, ejecuta `importar` y `renderizar` para publicar el nuevo mapa.
