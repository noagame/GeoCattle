# Desarrollo local de GeoCattle

Estado de referencia: 23 de octubre de 2026. Esta carpeta queda dedicada al
software, la recepción de telemetría, sus pruebas y la documentación del proyecto.

## Ejecutar y detener

Desde la raíz del proyecto, abre con doble clic:

1. [`Abrir-GeoCattle.cmd`](../Abrir-GeoCattle.cmd) para levantar PostgreSQL, la API y el proceso de alertas. La aplicación abre en http://localhost:8084/ y PostgreSQL usa el puerto 55434.
2. [`Iniciar-Captura.cmd`](../Iniciar-Captura.cmd) para recibir lecturas. Elige **Directo** para la T3 que recibe del collar o **Gateways** para la T3 base de los repetidores. El iniciador levanta los servicios preparados si la API está detenida.

La configuración local está en `.env.academic` y el acceso del prototipo en `.runtime/acceso_prototipo.json`. Conserva ambos archivos fuera de Git. Para un reinicio completo ejecuta `Detener-Prototipo.ps1` en PowerShell y vuelve a abrir los iniciadores que necesites.

## Acceso HTTPS desde otro dispositivo

Conecta el PC servidor y el otro dispositivo al mismo Wi-Fi. Puedes usar el punto de acceso de un celular o la **Zona con cobertura inalámbrica móvil** de Windows si es compatible con el adaptador. La conexión a Internet móvil sirve para compartir la red. GeoCattle usa la dirección privada del PC dentro de esa red.

1. Inicia [`Abrir-GeoCattle.cmd`](../Abrir-GeoCattle.cmd) y después [`Abrir-GeoCattle-LAN.cmd`](../Abrir-GeoCattle-LAN.cmd). Deja abierta la segunda consola. Imprime una URL como `https://192.168.43.20:8445/`. Si hay varias interfaces, ejecuta `.\Abrir-GeoCattle-LAN.cmd --bind IP_DEL_SERVIDOR` desde PowerShell y usa la IPv4 que muestra `ipconfig` para esa red.
2. Comparte únicamente el certificado público `.runtime/GeoCattle-LAN-CA.cer` con los dispositivos autorizados. Verifica su huella SHA-256 con `Get-FileHash .runtime/GeoCattle-LAN-CA.cer` e importa el certificado como autoridad de confianza según el sistema o el navegador. Los archivos de clave permanecen en `%LOCALAPPDATA%\GeoCattle\lan-tls` en el servidor.
3. Abre la URL HTTPS impresa e ingresa con una cuenta de GeoCattle. Los administradores usan MFA en este acceso. Para comprobar conexión y confianza del certificado, abre `/api/v1/health` en la misma URL.

Si cambias de Wi-Fi o el punto de acceso asigna otra IP al PC, reinicia el iniciador LAN. Emite un certificado para la nueva IP con la misma autoridad local. Comparte el nuevo enlace.

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
