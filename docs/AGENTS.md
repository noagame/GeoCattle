# Documentación

## Propósito y alcance

Este ámbito contiene operación, contratos, arquitectura, diseño V3, planificación y evidencias. `GeoCattle_Especificacion_V3/` conserva una copia de entrega de la especificación, `modelo-logico-v2/` contiene el modelo anterior y `evidencias/` conserva resultados fechados.

## Guía de trabajo

- Para un cambio vigente contrasta el [contrato de API](CONTRATO_API.md), las [migraciones](../database/AGENTS.md), los puntos de entrada y las pruebas antes de actualizar instrucciones o diagramas.
- Conserva las fechas y el alcance de informes históricos. Al documentar verificaciones, identifica el entorno y distingue resultados de software y de terreno. Usa nombres y datos ficticios en ejemplos nuevos.
- Verifica que rutas, comandos, nombres de entorno y vínculos locales coincidan con el repositorio. Consulta [Verificación](VERIFICACION.md) para reconocer las comprobaciones que sustentan una afirmación.
- Documenta por separado el cierre de la asociación, la baja reversible del collar y la eliminación sin historial en [Ciclo de vida de collares](CONTRATO_API.md#ciclo-de-vida-de-collares).
- Mantén alineados el [contrato de detecciones de collares](CONTRATO_API.md#detección-y-alta-de-collares), los pasos de [incorporación](DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora) y la [guía de captura](USB_COM5.md).
- Documenta el uso del perfil y las invitaciones en [Usuarios y registro](USUARIOS_Y_REGISTRO.md), las rutas y estados en [Contrato de API](CONTRATO_API.md) y los pasos de consola y configuración privada en [Operación](OPERACION.md).
- Mantén en [Verificación](VERIFICACION.md#carga-de-un-rebaño-de-validación) los comandos de carga ficticia, respaldo vinculado al destino y restauración en otra base.
- Mantén en [Operación](OPERACION.md#compartir-una-copia-del-prototipo) los pasos de exportación privada, importación en desarrollo y acceso con TOTP conservado o restablecido.
- Conserva en [Exportaciones tabulares](CONTRATO_API.md#exportaciones-tabulares) los filtros, límites y diferencias de representación entre Excel y las variantes CSV.
- Mantén en [Exportación del dueño](CONTRATO_API.md#exportación-del-dueño) las fórmulas K01–K12 y la distinción entre medición, aproximación y ensayo de campo pendiente.
- Mantén la instalación, atribución y alcance geográfico del mosaico local en [Mapa satelital](MAPA_SATELITAL.md).
- Mantén la instalación, atribución y cobertura del mapa OpenStreetMap local en [Mapa OpenStreetMap local](MAPA_OSM_LOCAL.md).
- Mantén los límites operativos del stack Docker y el ajuste opcional de WSL2 en [Desarrollo local](DESARROLLO_LOCAL.md#recursos-de-docker-desktop-y-wsl2). Documenta la liberación del volumen auxiliar del renderizador en [Mapa OpenStreetMap local](MAPA_OSM_LOCAL.md#liberar-espacio-y-actualizar).
- Mantén alineados el [plan del modo espejo](planificacion/PLAN_MODO_ESPEJO.md), la sección [Modo espejo](CONTRATO_API.md#modo-espejo) del contrato y la guía del espejo en [Despliegue en Debian](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#modo-espejo-el-pc-del-campo-como-sistema-principal).
- [Despliegue del servidor espejo](DESPLIEGUE_SERVIDOR_ESPEJO.md) divide el despliegue en la Parte A (administrador del servidor, hasta publicar la web y entregar el acceso SSH) y la Parte B (dueño del PC, desde `pc-admin` con TOTP hasta `pc-connect` y su verificación). Mantén el apéndice manual y la sección espejo de [Despliegue en Debian](DESPLIEGUE_DEBIAN_CLOUDFLARE.md) alineados con `scripts/mirror.py`.
- Documenta las bases en línea del espejo en [Despliegue en Debian](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#mapas) y la instalación de paquetes locales en las guías de cada mapa.
- Mantén el despliegue Debian con túnel, el traslado de bases, los respaldos y el enlace HTTPS de la estación en [Despliegue en Debian](DESPLIEGUE_DEBIAN_CLOUDFLARE.md). Alinea las rutas y permisos de captura con [USB](USB_COM5.md) y el [contrato de API](CONTRATO_API.md).

## Child DOX Index

- [diagramas/AGENTS.md](diagramas/AGENTS.md) — fuentes PlantUML, figuras del informe y catálogo de la base.
- [especificacion-v3/AGENTS.md](especificacion-v3/AGENTS.md) — requisitos, casos de uso, modelos y entregables V3.
- [planificacion/AGENTS.md](planificacion/AGENTS.md) — cronograma, correspondencia y evidencias de planificación.
- [evidencias/AGENTS.md](evidencias/AGENTS.md) — resultados fechados y mediciones reproducibles.
