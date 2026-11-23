# Diagramas del informe

Fuentes PlantUML y exportaciones SVG/PNG de las figuras de arquitectura y datos. Las figuras siguen la notación UML 2.5 y, para los modelos de datos, la notación pata de gallo (IE).

| Figura | Fuente | Contenido |
| --- | --- | --- |
| Componentes y dependencias | `componentes_uml.puml` | Componentes con «component», interfaces ofrecidas (círculo) y requeridas («use»), agrupados en subsistemas de campo, sede y cliente. |
| Topología propuesta del predio | `topologia_predio_uml.puml` | Diagrama de despliegue: nodos «device» y «executionEnvironment», artefactos y rutas de comunicación con su protocolo. |
| MER resumido | `mer_resumido.puml` | Entidades centrales con PK, FK, atributos clave y cardinalidades. |
| Mapa completo de la base | `modelo_bd_completo.puml` | Las tablas del esquema `public` agrupadas por dominio, con todas sus columnas y relaciones. Se genera desde el catálogo de PostgreSQL. |

## Regenerar

El mapa completo se genera leyendo solo el catálogo de la base (sin datos de negocio). Usa `DATABASE_URL` o, si falta, la base del prototipo nativo:

```sh
.venv/Scripts/python.exe docs/diagramas/generar_modelo_bd.py
```

Las imágenes se renderizan con la imagen Docker de PlantUML, desde `docs/diagramas/`:

```sh
docker run --rm -e PLANTUML_LIMIT_SIZE=16384 -v "$PWD:/data" plantuml/plantuml:1.2025.4 -tsvg -tpng -charset UTF-8 /data/*.puml
```

Una tabla nueva sin dominio aparece en el grupo «Otros»: clasifícala en `DOMAINS` dentro de `generar_modelo_bd.py`. Al cambiar componentes, servicios o equipos, actualiza la fuente `.puml` correspondiente y vuelve a renderizar.
