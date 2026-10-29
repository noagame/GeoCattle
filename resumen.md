# Resumen de cambios de GeoCattle

Actualizado: **25 de octubre de 2026**, America/Santiago. Base original de comparación: commit `2689c0a` de `noagame/GeoCattle`; la sección 8 describe la ampliación posterior a `3bf3d19`.

## Resultado

Se integró la recepción de datos físicos desde ESP32/LILYGO con el sistema existente y se mejoraron mapas, asociaciones, permisos, registro de colaboradores y alertas. Se mantiene PostgreSQL/PostGIS, el modelo V3 y la historia de lecturas. La actualización no publica la base local ni programa las placas.

## 1. Recepción USB y contrato de datos

- Decodificador de CSV V4 y JSON compacto V5, validación de campos y normalización al contrato de ingestión.
- Capturador serial con archivo JSONL diario, cola SQLite durable, identidad collar/sesión/secuencia, detección de duplicados y conflictos, y reintentos después de errores o desconexión.
- Confirmación de entrega únicamente después de persistir mediante la API. Cierre explícito de conexiones SQLite para liberar archivos en Windows.
- Conservación de GPS, diagnóstico NMEA, sensores, aceleración, actividad, movimiento, batería, USB, RSSI/SNR y metadatos recibidos.
- Hora del PC identificada como aproximada si el firmware no envía fecha UTC. Los mensajes sin fix conservan coordenadas nulas.
- Arranque local Windows, pausa de COM5, actualización de API y exportación diaria, sin incluir binarios ni credenciales locales.

Archivos principales: `adapters/lora_json.py`, `lora_usb.py`, `academic_bridge.py`, `scripts/prototype_windows.py`, `export_usb_day.py`, scripts PowerShell y `compose.usb.yaml`.

## 2. API y visualización de sensores

- Endpoints autenticados de resumen, historial paginado, registro diario y estado del receptor, aislados por predio.
- Última lectura y última posición GPS válida independientes; una muestra nueva sin fix no hace vigente una posición antigua.
- Pantalla Recepción de collares, gráficas, trayectoria filtrada por collar, detalle del JSON y exportación de la página visible.
- Resumen de batería según presencia, carga y USB; conteos de reposo/movimiento expresados como muestras, no como duración calculada.
- El estado de captura vencido no se presenta como receptor conectado.

## 3. Mapas y asociaciones históricas

- Corrección del ajuste de tamaño del mapa, cambio de capas y encuadre al mostrar y redimensionar vistas/modales.
- OpenStreetMap opcional, cuadrícula local, controles de recentrado y dibujo de polígonos con instrucciones, deshacer y limpieza.
- Tratamiento coherente de Leaflet `[latitud, longitud]` y GeoJSON `[longitud, latitud]`.
- Validación de collar/animal, sector/geocerca y vigencias; cierre del contexto anterior al reasignar y conservación de eventos y lecturas históricas.
- Rechazo de cortes retroactivos que dejarían telemetría fuera de su asociación original. Actualización de caché/paginación tras versionar geocercas.

## 4. Perfiles y registro de colaboradores

- Registro de trabajador y veterinario mediante invitación del dueño, con rol y predio fijados, vencimiento y uso único.
- Vista previa de invitación; distinción entre crear identidad nueva y aceptar con contraseña existente, sin sobrescribirla.
- Administración de colaboradores incorporados en contexto de soporte, sin emitir nuevas invitaciones en nombre del dueño.
- Comprobaciones de autoría para corrección/anulación sanitaria y mantenimiento de propuestas, confianza por acción y auditoría.
- KPI administrativo compatible con Windows: las mediciones del sistema no disponibles aparecen como ausencia de medición.
- Reinicio de vistas y formularios al cambiar el contexto autorizado de predio.

## 5. Configuración de alertas

- Botón **Configurar alertas** en Alertas y atención, compartiendo la misma configuración con Reglas del predio.
- Batería baja, temperatura superficial elevada, actividad reducida y ventana de evaluación, y cercanía al límite de geocerca.
- Escritura limitada al dueño y al administrador con predio seleccionado, también validada en el servidor.
- Metadatos de capacidades de lectura, validación de rangos, guardado con versión, auditoría y manejo explícito de conflictos 409 sin perder el borrador.
- Temperatura y actividad conservan su bloqueo de activación preventiva cuando falta validación de campo; se pueden guardar los umbrales.
- Las próximas lecturas usan la configuración nueva; guardar no borra eventos ni concluye su atención. Las reglas automáticas de comunicación y salida permanecen vigentes.

## 6. Documentación y datos conservados

Se actualizó el README y se añadieron guías de integración, visualización, usuarios, mapas/asociaciones, alertas y almacenamiento diario e histórico. Se incluyen capturas QA revisadas, sin contraseñas, factores MFA ni posiciones privadas. Los documentos nuevos generalizan rutas personales y ejemplos físicos identificables.

Los archivos originales de GitHub se conservan. Herramientas locales de firmware, compilaciones y descargas redundantes se retiraron antes de esta publicación con respaldo local. La aplicación y su contrato de recepción permanecen en el repositorio.

No se publican `.env*`, `.runtime/`, PostgreSQL local, colas SQLite, registros serie, credenciales, sesiones, factores MFA ni dependencias compiladas. Estos datos siguen en el equipo y no se eliminan por subir el código.

## 7. Verificación y límites

La verificación del 24 de octubre ejecutó **109 pruebas de backend correctas**, incluidas comprobaciones de roles, aislamiento, asociaciones, invitaciones y configuración de alertas. También se verificaron **26 pruebas de contrato/adaptadores** y la compilación TypeScript/Vite. Las pruebas de integración se ejecutan en una base QA aislada; la revisión visual incluye dueño, trabajador, veterinario y administrador, guardado de reglas y conflictos entre versiones.

La recepción física y la persistencia se comprobaron localmente. Eso no acredita calibración clínica, autonomía de batería, aceptación del productor, disponibilidad prolongada ni capacidad de una red de múltiples collares.

Pendientes relevantes:

- Validación de terreno de GPS, movimiento, temperatura y umbrales preventivos.
- Envío externo de invitaciones/avisos, integración LoRaWAN y codec/downlinks reales.
- Traslado de bovinos entre predios y desasignación independiente de collar sin reemplazo.
- Particionado temporal, archivo comprimido y resúmenes materializados; el informe de almacenamiento es una propuesta, no una función aplicada.
- Preparación independiente de cada nuevo entorno Windows; el clon no incluye los datos ni binarios privados del prototipo.

Ver [Configuración de alertas](docs/CONFIGURACION_ALERTAS.md), [revisión de mapas, asociaciones y perfiles](docs/REVISION_MAPAS_ASOCIACIONES_PERFILES.md), [registro de usuarios](docs/USUARIOS_Y_REGISTRO.md) y [contrato de integración](docs/CONTRATO_API.md).

## 8. Captura por identidad USB y Docker para Windows/Linux — 25 de octubre

- Captura con `Iniciar-Captura.cmd` y reconocimiento de la receptora por VID/PID y número de serie USB (o ubicación cuando no hay serie), sin depender de un número COM fijo. La vinculación inicial exige un paquete de receptor con información radio.
- Reconexión a la misma placa y exclusión de lectores duplicados mediante un bloqueo de archivo compatible con Windows/Linux; se conserva el archivo diario y la cola durable.
- Arranque común `scripts/docker_project.py` para preparar, iniciar, detener, consultar y respaldar Docker sin Bash en el anfitrión. Simulación usa `.env`; desarrollo físico Docker usa `.env.docker`, otros puertos y otra carpeta de captura. La instancia nativa y sus datos se conservan.
- Objetivos Docker `runtime` y `test`, variables de configuración conectadas a los servicios, finales LF para scripts POSIX, `tzdata` para el capturador y CSP de OpenStreetMap corregida.
- Inicialización idempotente de las extensiones `pg_trgm`/`hstore` antes de ChirpStack; comprobación de sus tablas, Redis y recorrido MQTT hasta PostgreSQL y API.
- Ejecutable de prueba `qa/docker_portability.py` y acceso Windows `Probar-Docker.cmd`, con configuración, base y volúmenes QA separados. La prueba no abre USB ni consulta la base nativa y no elimina volúmenes.

La verificación terminó correctamente en contenedores **Linux x86_64 sobre Docker Desktop en Windows**: **113 pytest backend**, **94 unittest de adaptadores/hardware** y **126 comprobaciones HTTP**, además de worker independiente, MQTT y persistencia de **589 lecturas QA** antes y después del reinicio. También pasaron **90 unittest en Windows**. Los conteos corresponden a suites distintas y algunas se repiten entre sistemas; no representan pruebas de campo ni carga física de múltiples collares.

La captura USB permanece en el anfitrión. No se ha probado otra máquina física, ARM, USB real hacia Docker ni una red LoRaWAN física. El primer intento fallido y su corrección quedan documentados; no se modificó la protección temporal de las nuevas asignaciones de collar.

Ver [revisión Docker y portabilidad](docs/REVISION_DOCKER_PORTABILIDAD.md) y [evidencia QA sin credenciales](docs/evidencias/docker_portabilidad_2026-10-25.json). Se conservan los archivos originales y los datos privados fuera de Git.

## 9. Compatibilidad del emisor de 45 segundos — 28 de octubre de 2026

- Corregido el máximo de `p` en el adaptador JSON V5: `45000` ms. El límite anterior de `40000` ms rechazaba mensajes válidos del firmware actualizado.
- Se mantiene la compatibilidad con 30–40 segundos y las validaciones de tipos, sensores, flags, batería, radio y tamaño del paquete.
- Añadida regresión para paquetes de 45 segundos, tanto directos como con el sobre del receptor, y recepción/archivo simulado. Se ejecutaron 57 pruebas de captura y adaptadores con resultado correcto, sin utilizar placas en esas pruebas.
- En la comprobación física posterior se recuperaron dos líneas rechazadas conservando su hora de recepción; se respaldó la cola SQLite antes del rescate y se verificó la deduplicación. La captura reanudada recibió nuevas lecturas y confirmó su persistencia mediante la API.
- Los registros serie, datos recuperados, respaldos y credenciales permanecen privados en `.runtime/`; no se añaden al repositorio. Este cambio no modifica firmware ni requiere reiniciar la API.
- Se incluye `Abrir-GeoCattle.cmd` para abrir la aplicación nativa preparada sin iniciar la captura USB.

## Organización del desarrollo — 29 de octubre de 2026

Se separan las áreas de trabajo mediante `dev/software`, `dev/hardware-captura` y `develop`, conservando `main` como versión estable y las carpetas existentes. Fabián (`noagame`) y Boris (`BorBP`) pueden modificar software y cualquier módulo necesario; los contratos compartidos se revisan entre ambos. La documentación y CODEOWNERS distinguen coordinación de área de permisos de edición.

Se añaden guía de colaboración, plantilla de PR y tres controles de CI: frontend, captura/contratos y reglas de dominio. El trabajo de lotes y selección de receptores que estaba pendiente se conserva en la rama de hardware como desarrollo en curso, separado de la versión estable. No se modifica la base operativa ni se programan placas. Las restricciones obligatorias en GitHub necesitan activación con permisos de administración; los archivos de CI y CODEOWNERS no las habilitan por sí solos.
