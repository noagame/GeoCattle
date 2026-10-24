# Visualización de telemetría física en GeoCattle

Actualizado: 23 de octubre de 2026, hora de Chile.

## Resultado verificado

Se comprobó el recorrido collar T-Beam → LoRa → T3 en COM5 → puente USB → API → PostgreSQL → interfaz. Después del cambio de antena ya llegaron posiciones GPS válidas. Se verificaron lecturas con posición válida, satélites usados, HDOP, temperatura y actividad. La evidencia detallada de las capturas se conserva de forma privada en el equipo. El contador de recepción continuó aumentando durante la verificación.

Esa lectura informa batería ausente y USB presente. La interfaz conserva ese estado y no muestra porcentajes inventados. Las lecturas anteriores con batería siguen mostrando su tensión y porcentaje estimado.

## Uso

1. Abrir http://localhost:8084/#hardware e iniciar sesión con la cuenta del proyecto.
2. El resumen superior muestra la última lectura de cada collar del predio, independiente de la fecha del historial.
3. Seleccionar REAL01 para ver sus gráficas y trayectoria. La fecha limita el historial; hay 100 lecturas por página.
4. Pulsar «Ver todos los datos» o «Ver datos» en una fila para revisar sensores, diagnóstico y JSON almacenado.
5. «Exportar página JSONL» descarga los registros normalizados visibles. No exporta automáticamente todo el día.
6. El registro diario muestra los últimos 30 días. Pulsar un día cambia la fecha y el collar del historial.

## Campos utilizados

| Dato recibido | Uso en la interfaz |
|---|---|
| Identificador, sesión y secuencia | Identidad del paquete y detalle; las secuencias pueden repetirse entre reinicios |
| Temperatura | Resumen, tabla, gráfica y mínimos/máximos diarios |
| Aceleración X/Y/Z | Detalle de cada lectura |
| RMS de actividad | Resumen, gráfica, tabla y detalle |
| Reposo/movimiento/sin clasificar | Resumen, tabla y conteos diarios |
| Latitud/longitud y fix válido | Mapa por collar, trayectoria filtrada, tabla y detalle |
| Satélites usados, HDOP y edad de posición | Resumen GPS, tabla y detalle |
| Bytes NMEA, sentencias válidas y errores | Detalle de diagnóstico GPS |
| Tensión, porcentaje estimado, presencia y carga de batería | Resumen, tabla, gráfica histórica y detalle |
| Alimentación USB | Resumen, tabla y detalle |
| RSSI y SNR | Tabla y detalle de recepción LoRa |
| Motivo e intervalo de transmisión | Tabla y detalle; no es una orden enviada al collar |
| Tiempo encendido, protocolo y flags | Detalle del paquete |
| Receptor, hora de captura, hora de guardado y origen | Trazabilidad del registro |
| Metadatos adicionales almacenados | JSON completo del registro |

Satélites visibles y C/N₀ existen en el diagnóstico serie del emisor, pero el protocolo de radio actual no los transmite. No se presentan como datos disponibles en la base.

## Interpretación y límites

- Las posiciones sin fix no generan puntos ficticios. Se conserva la última posición válida y se distingue como histórica al vencer su ventana de vigencia.
- El mapa funciona con cuadrícula local. La cartografía externa es opcional y requiere Internet.
- Seleccionar un collar evita unir trayectorias de dispositivos distintos. La trayectoria y las gráficas corresponden a la página consultada, no necesariamente al día completo.
- Las gráficas interrumpen el trazado ante datos ausentes, cambios de sesión o pausas largas. Los conteos de reposo y movimiento son muestras, no duraciones: hay transmisiones adicionales por movimiento.
- La temperatura es la lectura del sensor; no se transforma en temperatura corporal ni diagnóstico clínico.
- El firmware no transmite fecha UTC. La observación se fecha con la primera recepción del PC y se identifica como aproximada; la hora de guardado en el servidor permanece separada.
- En la primera revisión el collar estaba sin bovino. Posteriormente se verificó su asociación vigente mediante el flujo de asignaciones; las lecturas previas sin animal se conservaron. Véase REVISION_MAPAS_ASOCIACIONES_PERFILES.md para la semántica histórica.

## Implementación

- API `/hardware/overview`: última lectura y última posición válida independientes por collar, aisladas por predio. Consultas por dispositivo usando el índice existente `telemetry_device_time`.
- API `/hardware/telemetry`: incluye ahora `activity_index`; conserva paginación, filtros y metadatos completos.
- API `/hardware/daily`: intervalo predeterminado de 30 días, filtro por collar, posiciones válidas, conteos de movimiento y extremos de temperatura. La agregación sigue calculándose desde la telemetría; no se implementó archivo ni resumen materializado para grandes volúmenes.
- API `/hardware/receiver`: un estado del puente de más de 30 segundos no se informa como conectado. Se toleran archivos de estado UTF-8 con BOM.
- La ficha del bovino puede mostrar el mismo detalle de sensores cuando existe una lectura asociada.
- No se cambió el protocolo ni se cargó firmware en las placas durante este trabajo.

## Validación

- Compilación TypeScript y Vite correctas.
- 26 pruebas del contrato, decodificador y archivo USB correctas; 4 pruebas nuevas de PostgreSQL correctas. Las pruebas de integración revierten sus datos y se comprobó que no quedaron collares de prueba persistidos.
- Pruebas HTTP sobre la API en ejecución: resumen, historial, registro diario y receptor con respuesta 200; acceso anónimo rechazado; límites de consultas y filtros comprobados.
- Verificación de navegador: lectura real con posición, diagnóstico completo y JSON; gráficas de temperatura, actividad y batería con datos reales y sin avisos de error.
- Captura COM5 activa y nuevas posiciones confirmadas en PostgreSQL tras la actualización.

## Inicio y actualización

La versión nueva ya está activa. Si se necesita reiniciar solo la API después de un cambio de código, ejecutar en PowerShell normal la línea completa:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ruta\GeoCattle\Actualizar-Visualizacion.ps1"
```

Para capturar en primer plano, usar `Iniciar-Captura-COM5.ps1`, con el Monitor Serie y Plotter cerrados. No abrir dos lectores del mismo puerto. Mantener la T3 en el cable de datos y la T-Beam alimentada con batería o el cable de alimentación disponible.
