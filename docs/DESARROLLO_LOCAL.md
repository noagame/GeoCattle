# Desarrollo local de GeoCattle

Estado de referencia: 23 de octubre de 2026. Esta carpeta queda dedicada al
software, la recepción de telemetría, sus pruebas y la documentación del proyecto.

## Ejecutar y detener

Desde la raíz del proyecto, abre con doble clic:

1. [`Abrir-GeoCattle.cmd`](../Abrir-GeoCattle.cmd) para levantar PostgreSQL, la API y el proceso de alertas. La aplicación abre en http://localhost:8084/ y PostgreSQL usa el puerto 55434.
2. [`Iniciar-Captura.cmd`](../Iniciar-Captura.cmd) para recibir lecturas. Elige **Directo** para la T3 que recibe del collar o **Gateways** para la T3 base de los repetidores. El iniciador levanta los servicios preparados si la API está detenida.

Para preparar un equipo nuevo, sigue la [instalación desde cero en Windows](../README.md#instalación-desde-cero-en-windows). `scripts\prototype_windows.py init` crea la base local con las credenciales de `.env.academic`.

La configuración local está en `.env.academic` y el acceso del prototipo en `.runtime/acceso_prototipo.json`. Conserva ambos archivos fuera de Git. Para un reinicio completo ejecuta `Detener-Prototipo.ps1` en PowerShell y vuelve a abrir los iniciadores que necesites.

## Recursos de Docker Desktop y WSL2

El arranque Docker habitual ejecuta PostgreSQL/PostGIS, la API, el worker y Nginx, más la migración inicial. Los cuatro servicios permanentes tienen un tope combinado de 1.088 MiB y 3,25 CPU. Los topes se aplican por contenedor y Docker Desktop usa memoria adicional para WSL2. Nginx y Uvicorn usan un proceso de trabajo cada uno. Compose rota los logs de los contenedores con un máximo de tres archivos de 10 MB cada uno. MQTT y ChirpStack se activan con `--profile iot` y `--profile lorawan` en `scripts/docker_project.py`. La generación de cartografía OSM tiene su propio flujo. [Mapa OpenStreetMap local](MAPA_OSM_LOCAL.md).

En un equipo Windows de 16 GB, este ejemplo de `%USERPROFILE%\.wslconfig` deja hasta 6 GB y 4 procesadores lógicos para el conjunto de distribuciones WSL2:

```ini
[wsl2]
memory=6GB
processors=4
swap=2GB

[experimental]
autoMemoryReclaim=gradual
```

Para aplicar el cambio, guarda el trabajo abierto en tus distribuciones y ejecuta `wsl --shutdown` antes de volver a abrir Docker Desktop. El comando detiene las distribuciones WSL2. La importación del mapa OSM puede necesitar más memoria de WSL2 si otros contenedores están activos. [Configuración de WSL](https://learn.microsoft.com/windows/wsl/wsl-config#wslconfig).

Consulta `docker stats --no-stream` para ver consumo en ejecución y `docker system df -v` para revisar uso en disco. Estos comandos de limpieza actúan sobre la caché que no se haya usado en siete días y las imágenes colgantes, respectivamente:

```sh
docker builder prune --filter until=168h
docker image prune --filter dangling=true
```

Los volúmenes guardan bases de datos y colas. Para liberar espacio de la base auxiliar de OSM, sigue el procedimiento dedicado. [Liberar espacio de OpenStreetMap](MAPA_OSM_LOCAL.md#liberar-espacio-y-actualizar).

## Instalar el mapa satelital

Genera el mosaico con `python scripts/preparar_mapa_satelital.py --araucania` desde la raíz y con las dependencias del conversor instaladas en un entorno aparte. El inicio nativo, Vite y Docker sirven `.runtime/mapa-satelital/` sin copiar las imágenes al build. Recarga la vista del mapa o pulsa **Reintentar mapa** cuando termine. [Fuente y verificación](MAPA_SATELITAL.md).

## Acceso HTTPS desde otro dispositivo

Conecta el PC servidor y el otro dispositivo al mismo Wi-Fi. Puedes usar el punto de acceso de un celular o la **Zona con cobertura inalámbrica móvil** de Windows si es compatible con el adaptador. La conexión a Internet móvil sirve para compartir la red. GeoCattle usa la dirección privada del PC dentro de esa red.

1. Inicia [`Abrir-GeoCattle.cmd`](../Abrir-GeoCattle.cmd) y después [`Abrir-GeoCattle-LAN.cmd`](../Abrir-GeoCattle-LAN.cmd). Deja abierta la segunda consola. Imprime una URL como `https://192.168.43.20:8445/`. Si hay varias interfaces, ejecuta `.\Abrir-GeoCattle-LAN.cmd --bind IP_DEL_SERVIDOR` desde PowerShell y usa la IPv4 que muestra `ipconfig` para esa red.
2. Comparte únicamente el certificado público `.runtime/GeoCattle-LAN-CA.cer` con los dispositivos autorizados. Verifica su huella SHA-256 con `Get-FileHash .runtime/GeoCattle-LAN-CA.cer` e importa el certificado como autoridad de confianza según el sistema o el navegador. Los archivos de clave permanecen en `%LOCALAPPDATA%\GeoCattle\lan-tls` en el servidor.
3. Abre la URL HTTPS impresa e ingresa con una cuenta de GeoCattle. Los administradores usan MFA en este acceso. Para comprobar conexión y confianza del certificado, abre `/api/v1/health` en la misma URL.

Si solo se corta Internet y ambos equipos siguen en el mismo Wi-Fi, el enlace local sigue funcionando mientras el servidor conserve su IP. Si el PC se reconecta y recibe otra dirección, vuelve a abrir `Abrir-GeoCattle-LAN.cmd`. El iniciador detecta la IP en cada apertura, muestra la URL incluso cuando el servidor ya está activo y guarda el último enlace verificado en `.runtime/GeoCattle-LAN-URL.txt`. Para una IP nueva emite un certificado firmado por la misma autoridad local. Comparte el nuevo enlace con los clientes.

Si el cliente recibe un tiempo de espera, revisa que el punto de acceso permita comunicación entre dispositivos y que el firewall de Windows permita TCP `8445` desde la subred del servidor. Para autorizarlo de forma acotada, abre PowerShell como administrador y reemplaza `IP_DEL_SERVIDOR` y `SUBRED_CIDR` por los valores de esa conexión:

```powershell
New-NetFirewallRule -DisplayName 'GeoCattle HTTPS LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8445 -LocalAddress IP_DEL_SERVIDOR -RemoteAddress SUBRED_CIDR
```

Si cambia la red, actualiza o retira esa regla. Ctrl+C en la consola LAN detiene el acceso HTTPS. El prototipo local sigue en `localhost:8084` y PostgreSQL conserva su puerto en loopback.

En Ubuntu o Debian, puedes comprobar el certificado sin instalarlo en el almacén del sistema. Copia el archivo público y ejecuta:

```bash
openssl x509 -inform DER -in GeoCattle-LAN-CA.cer -out GeoCattle-LAN-CA.pem
curl --cacert GeoCattle-LAN-CA.pem https://IP_DEL_SERVIDOR:8445/api/v1/health
```

## Captura con doble clic e identidad USB

Cierra el Monitor Serie y el Plotter de Arduino. Conecta la T3 receptora por USB de datos y enciende el emisor. En el primer enlace, el perfil del modo se guarda al recibir un mensaje válido con información de radio. Usa VID/PID y número de serie USB cuando está disponible. Si Windows cambia el COM, el capturador busca la misma identidad.

Deja abierta la ventana de captura. Ctrl+C detiene el lector en primer plano. Para pausar uno en segundo plano, usa `Pausar-Captura-COM5.ps1` desde PowerShell. Al abrir `Iniciar-Captura.cmd` de nuevo puedes elegir un modo para el mismo capturador compatible. La cola local usa un bloqueo exclusivo para evitar lectores duplicados.

Desde una consola, el mismo iniciador acepta `--receiver-mode direct` o `--receiver-mode gateways` para omitir el menú. Si necesitas restringir la búsqueda a un puerto concreto, puedes añadir `--port COMx`. La identidad ya guardada se sigue comprobando.

El estado local registra `last_line_at` para cualquier línea serial, `last_packet_at` para el último paquete válido de la ejecución y `last_capture` para la última lectura única archivada. Estos campos ayudan a distinguir actividad USB, recepción y persistencia.

## Incorporar un collar por USB o LoRa

1. Abre el prototipo en Chrome o Edge de escritorio desde `http://localhost:8084` o por HTTPS en la LAN. Inicia sesión como dueño o administrador y selecciona el predio físico donde quedará el collar.
2. Conecta el collar con un cable USB de datos **al equipo donde está abierto el navegador**. Cierra el Monitor Serie, el Plotter de Arduino o cualquier captura que use ese puerto. En **Collares y dispositivos → Collares detectados**, pulsa **Detectar collar por USB**. En el selector de puertos, elige el collar y concede acceso. La receptora T3 puede quedar conectada, pero no selecciones su puerto.
3. La web registra la detección en el predio activo de tu sesión y abre **Agregar al sistema**. Revisa el identificador, el nombre sugerido y el intervalo antes de confirmar. Si cierras el formulario de alta, la detección queda pendiente en la bandeja.
4. Asigna el collar a un bovino cuando esté listo. Las nuevas lecturas llegan por la T3 mediante LoRa.

El [firmware con identificación USB](../firmware/README.md#identidad-y-alta-por-usb) responde a una consulta. Con el firmware anterior que imprime JSON V5, la detección espera hasta 55 segundos y toma el identificador y el intervalo del primer paquete válido. Para el collar histórico, el resultado es `REAL01` con un intervalo de 45 segundos.

**Alternativa USB en Windows:** si Web Serial no está disponible o necesitas reutilizar como collar una T3 que estaba registrada como receptora Directa, ejecuta [`Registrar-Collar-USB.cmd`](../Registrar-Collar-USB.cmd) y sigue sus indicaciones. Este asistente usa `INGEST_KEY` de `.env.academic`. Si hay varios predios físicos activos, elige el predio y confirma si quieres recordarlo como `INGEST_FARM_ID`. Para cambiarlo, edita o borra esa opción o pasa `--farm-id` al ejecutar `scripts/register_collar_usb.py`. Reinicia la captura LoRa si cambia la configuración guardada. Si confirmas la reutilización de la T3, el asistente archiva su perfil de receptora en `.runtime/capture/` y cambia la recepción a Gateways. La placa base de Gateways nunca se acepta como collar. Abre el predio elegido en la web para aprobar el collar.

**Detección por LoRa:** inicia `Iniciar-Captura.cmd` y espera un paquete válido del collar; aparecerá en **Collares detectados** del predio configurado para la captura. Desde allí puedes aprobar el alta o descartar la detección.

## Incorporar un gateway por USB

1. Carga `firmware/GeoCattle_Gateway` en el XIAO ESP32-S3 con RadioLib 7.8.1. Todos los gateways usan el mismo binario. [Firmware](../firmware/README.md#gateways-con-nodo-asignado-por-geocattle)
2. En Chrome o Edge, abre **Gateways instalados** en el predio correspondiente, conecta solo el gateway por USB y presiona **Detectar gateway por USB**.
3. En **Agregar al sistema**, revisa el nombre sugerido y, si quieres, marca la ubicación. Al confirmar, GeoCattle reserva un nodo libre, lo configura en la placa por USB y completa el alta cuando la placa responde.

Como alternativa, ejecuta `Registrar-Gateway-USB.cmd` e inicia sesión con una cuenta de dueño o administrador. La placa base de Gateways y las receptoras no se aceptan como gateway. Un predio admite dos gateways vinculados.

## Dónde agregar funcionalidades

| Área | Ubicación |
|---|---|
| Interfaz del prototipo | `frontend/src/HardwarePage.tsx` |
| Detalle de sensores | `frontend/src/TelemetryView.tsx` |
| Mapa | `frontend/src/Map.tsx` |
| API de hardware | `backend/geocattle/hardware_api.py` |
| Reglas de dominio e ingestión | `backend/geocattle/domain.py` |
| Modelos y validaciones API | `backend/geocattle/models.py`, `schemas.py` |
| Migraciones | `database/migrations/` |
| Decodificación JSON y captura COM5 | `adapters/lora_json.py`, `lora_usb.py` |
| Arranque local Windows | `scripts/prototype_windows.py` |
| Pruebas del contrato y puente | `qa/test_lora_json.py`, `test_lora_usb.py`, `test_esp32_contract.py` |
| Pruebas de consultas de hardware | `qa/test_hardware_api.py` |

El [contrato de integración](CONTRATO_API.md#captura-radio-json-v5) especifica los
campos del collar. El estado y las limitaciones de la demostración están en
[VISUALIZACION_TELEMETRIA.md](VISUALIZACION_TELEMETRIA.md). Conservar el aislamiento
por predio, la identidad collar/sesión/secuencia y el historial inmutable.

## Comprobar cambios

Las dependencias de aplicación se conservaron: `.venv/` y
`frontend/node_modules/`. También se conservó `frontend/dist/`, que sirve la
aplicación local.

```powershell
# Desde la raíz: pruebas sin necesitar placas ni escribir datos reales.
.\.venv\Scripts\python.exe -m unittest qa.test_lora_json qa.test_lora_usb qa.test_esp32_contract qa.test_academic_bridge

# Desde frontend: comprobar TypeScript y compilar la interfaz.
Set-Location frontend
npm run build
Set-Location ..
```

Si Node/npm no están en PATH, usar la instalación disponible en el equipo.
No se necesita reinstalar ni compilar firmware para ejecutar estas pruebas.
Después de compilar la interfaz, recargar el navegador con Ctrl+F5. Después de
cambiar Python de la API, detener el prototipo con `Detener-Prototipo.ps1` y volver a abrir `Abrir-GeoCattle.cmd`. Si necesitas captura, abre también `Iniciar-Captura.cmd`.

Las pruebas de `qa/test_hardware_api.py` se omiten por defecto: necesitan una
base PostgreSQL explícita y `GEOCATTLE_TEST_DATABASE=1`. Sus fixtures se revierten;
no sustituir esa reversión por borrados de capturas reales. Las pruebas generales
de integración del backend se deben ejecutar contra una base de simulación
separada, según `docs/VERIFICACION.md`.

## Datos y evidencia conservados

- `.runtime/capture/`: archivo diario JSONL, cola SQLite, confirmaciones y estado USB.
- `.runtime/pgdata-academic/`: datos PostgreSQL; `.runtime/postgres16/`: binarios activos.
- Logs de servicios, diagnósticos GPS, registros de compilación/carga y manifiestos históricos en `.runtime/`.
- Documentación, diagramas y fuentes canónicas en `docs/especificacion-v3/`.
- Informes de integración, almacenamiento, implementación, planificación y visualización.
- Código de aplicación y pruebas automatizadas; configuración, migraciones y herramientas de operación.

Respaldar PostgreSQL con `pg_dump`; no copiar su directorio de datos mientras
está escribiendo. No borrar toda `.runtime/`: contiene información del proyecto
y servicios necesarios. Los archivos privados y datos locales siguen excluidos
por `.gitignore`.

## Limpieza del 23 de octubre de 2026

Se retiraron del árbol del proyecto aproximadamente 939 MB de archivos:

- Sketches y utilidades de compilación, carga y diagnóstico de placas.
- Compilaciones de emisor y receptor, biblioteca Arduino local y cachés de herramientas.
- Instaladores PostgreSQL/PostGIS ya extraídos. Los binarios en uso permanecen.
Se conservaron **todos los archivos originales de GitHub**, incluidas las copias
documentales y el archivo de referencia `docs/planificacion/node_modules`. La
verificación final contra `origin/main` y el inventario Git no detectó archivos
originales ausentes. Solo se retiraron agregados locales posteriores al clonado.

La revisión automática rechazó el borrado directo, por lo que la retirada es
reversible. No se afirma haber liberado espacio del disco: los archivos se
movieron fuera de esta carpeta a:

```text
<carpeta-local-de-respaldo>\GeoCattle-retirados-2026-10-23
```

Los fuentes, scripts y documentos retirados también tienen un respaldo ZIP
verificado por SHA-256, sin credenciales ni base de datos:

```text
<carpeta-local-de-respaldo>\GeoCattle-respaldo-limpieza-2026-10-23.zip
```

El inventario y los hashes están en `.runtime/limpieza-2026-10-23.json` y en
`GeoCattle-limpieza-2026-10-23.json` junto a ese respaldo. Estos códigos son
históricos: no acreditan coincidir con la última versión cargada manualmente
en las placas. No restaurarlos ni volver a cargarlos como parte del arranque
del software. Si se retoma la programación del hardware, recuperar solo lo
necesario y validar primero la versión y las dependencias de Arduino.
