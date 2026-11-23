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
- Conserva en [Exportaciones tabulares](CONTRATO_API.md#exportaciones-tabulares) los filtros, límites y diferencias de representación entre Excel y las variantes CSV.
- Mantén en [Exportación del dueño](CONTRATO_API.md#exportación-del-dueño) las fórmulas K01–K12 y la distinción entre medición, aproximación y ensayo de campo pendiente.
- Mantén la instalación, atribución y alcance geográfico del mosaico local en [Mapa satelital](MAPA_SATELITAL.md).
- Mantén la instalación, atribución y cobertura del mapa OpenStreetMap local en [Mapa OpenStreetMap local](MAPA_OSM_LOCAL.md).
- Mantén los límites operativos del stack Docker y el ajuste opcional de WSL2 en [Desarrollo local](DESARROLLO_LOCAL.md#recursos-de-docker-desktop-y-wsl2). Documenta la liberación del volumen auxiliar del renderizador en [Mapa OpenStreetMap local](MAPA_OSM_LOCAL.md#liberar-espacio-y-actualizar).

## Child DOX Index

- [especificacion-v3/AGENTS.md](especificacion-v3/AGENTS.md) — requisitos, casos de uso, modelos y entregables V3.
- [planificacion/AGENTS.md](planificacion/AGENTS.md) — cronograma, correspondencia y evidencias de planificación.
- [evidencias/AGENTS.md](evidencias/AGENTS.md) — resultados fechados y mediciones reproducibles.
