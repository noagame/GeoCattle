# Operación local y preparación del piloto

## Ambientes y credenciales

`scripts/configure.py` genera `.env` para simulación. `scripts/configure.py --environment development` genera `.env.academic`, base y credenciales independientes para capturas académicas reales; no carga datos sintéticos. `scripts/configure.py --environment production` genera `.env.pilot` con proyecto Compose, base, volumen, puertos y secretos distintos. Conservar ambos archivos privados. La carga de demo y las rutas/source `sim` se bloquean fuera de simulación.

```bash
python3 scripts/configure.py --environment production
bash scripts/compose.sh --env-file .env.pilot --profile tls up -d --build
# Crear un predio/propietario real sin cargar demo:
bash scripts/compose.sh --env-file .env.pilot --profile tools run --rm bootstrap \
  python -m geocattle.bootstrap --username propietario@predio.local --farm 'Predio'
```

Para el bootstrap, `ADMIN_PASSWORD` se toma de `.env.pilot`; no se introduce como argumento. El perfil TLS usa Caddy con una autoridad local, accesible por `https://localhost:8444` para piloto. Exportar y confiar en el certificado CA en los equipos autorizados antes de usarlo; no se modifica automáticamente el almacén de confianza del computador. Para LAN real, configurar nombre del servidor, certificado y dirección de escucha específicos del predio, actualizar `ALLOWED_ORIGINS` y mantener `COOKIE_SECURE=true`. Para acceso remoto, definir el canal autenticado y la administración de certificados. El despliegue inicial sólo escucha en loopback.

No utilizar las credenciales de simulación en piloto. No registrar claves OTAA en bitácoras, notas de alerta ni respuestas API. Las claves de radio se aprovisionan en ChirpStack y nodos por un procedimiento separado.

## Correo SMTP de invitaciones

1. Edita el archivo privado de la instalación. Los lanzadores nativos de Windows usan `.env.academic`. Docker usa el archivo indicado con `--env-file`, por ejemplo `.env.docker` con el lanzador Linux, `.env` en simulación predeterminada o `.env.pilot` para el piloto.
2. Para Gmail, activa la verificación en dos pasos de la cuenta remitente y crea una contraseña de aplicación. Copia esa contraseña sin los espacios de presentación en `SMTP_PASSWORD` del archivo privado. Usa la misma cuenta para `SMTP_USERNAME` y `SMTP_FROM`, o un alias de envío que el proveedor autorice. [Contraseñas de aplicación de Google](https://support.google.com/accounts/answer/185833?hl=es)
3. Guarda las variables del proveedor. Este ejemplo usa direcciones ficticias.

   ```dotenv
   INVITATION_EMAIL_ENABLED=false
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_TLS_MODE=starttls
   SMTP_USERNAME=geocattle-ejemplo@gmail.com
   SMTP_PASSWORD=REEMPLAZAR_EN_EL_ARCHIVO_PRIVADO
   SMTP_FROM=geocattle-ejemplo@gmail.com
   SMTP_TIMEOUT_SECONDS=8
   INVITATION_BASE_URL=http://localhost:8084
   ```

   Gmail también admite `SMTP_PORT=465` con `SMTP_TLS_MODE=ssl`. Con otro proveedor usa el host y puerto de su servicio SMTP y una cuenta autorizada. Microsoft 365 usa `smtp.office365.com:587` con STARTTLS. Outlook.com usa `smtp-mail.outlook.com:587` con STARTTLS y OAuth. Cuando el proveedor exige OAuth, usa un relay TLS compatible aprobado por el operador. Si el relay autoriza la red de origen, deja `SMTP_USERNAME` y `SMTP_PASSWORD` vacíos. [Configuración de envío SMTP de Microsoft 365](https://learn.microsoft.com/exchange/mail-flow-best-practices/how-to-set-up-a-multifunction-device-or-application-to-send-email-using-microsoft-365-or-office-365)

4. Ajusta `INVITATION_BASE_URL` a la dirección que abrirá el invitado. Usa `http://localhost:8084` solo para pruebas en el mismo PC, o el puerto publicado de Docker en loopback durante simulación. Para Windows LAN copia la URL HTTPS escrita por `Abrir-GeoCattle-LAN.cmd` en `.runtime/GeoCattle-LAN-URL.txt`; el dispositivo invitado debe estar en la red y confiar en el certificado de GeoCattle. Si cambia la IP, actualiza el archivo privado. En Docker publicado usa la URL HTTPS del proxy que sirve la interfaz. La API y el worker deben leer la misma URL. Conserva `SESSION_SECRET` y `MFA_ENCRYPTION_KEY` al editar SMTP. [Acceso HTTPS en Windows](DESARROLLO_LOCAL.md#acceso-https-desde-otro-dispositivo)
5. Prueba el envío a una dirección que controlas antes de activar las invitaciones.

   Ejecuta en Windows nativo desde la raíz.

   ```powershell
   py -3 scripts/account_maintenance.py smtp-test --to destinatario@example.test
   ```

   En Docker, ejecuta desde la raíz con el mismo archivo y perfiles de la instalación.

   ```bash
   docker compose --env-file .env.docker run --rm --no-deps --build worker python -m geocattle.account_maintenance smtp-test --to destinatario@example.test
   ```

   El comando envía un mensaje de prueba sin crear cuentas ni invitaciones. Informa si el servidor aceptó el mensaje o qué etapa SMTP falló. Verifica también la recepción en el buzón. Sustituye el destinatario ficticio al ejecutarlo.

6. Cambia `INVITATION_EMAIL_ENABLED=true`. Respalda la base antes del arranque que aplica las migraciones de la nueva versión. En Windows, ejecuta `.\Detener-Prototipo.ps1` y vuelve a abrir `Abrir-GeoCattle.cmd` y el lanzador LAN si lo usas. En Docker, vuelve a ejecutar el arranque con el mismo archivo y perfiles.

   ```bash
   docker compose --env-file .env.docker up -d --build
   ```

Las instalaciones con `GMAIL_SMTP_FROM` y `GMAIL_SMTP_APP_PASSWORD` conservan su configuración de Gmail SSL 465 si `SMTP_HOST` queda vacío y se mantienen el modo y puerto predeterminados. El worker registra el identificador, la clase de error y el código numérico SMTP. Los rechazos definitivos cierran el intento. Ante fallos temporales, la cola conserva el correo hasta tres intentos, con demoras de uno y dos minutos. La aceptación SMTP acredita entrega al servidor de correo.

## Restablecer el autenticador por consola

Usa la consola del anfitrión cuando el titular haya perdido el autenticador y sus códigos de recuperación. Verifica el correo de acceso y el entorno. Aplica la migración 010 mediante el arranque o la migración de la instalación antes de ejecutar el comando.

En Windows nativo, ejecuta desde la raíz con PostgreSQL del prototipo en ejecución.

```powershell
py -3 scripts/account_maintenance.py mfa-reset --email administrador@example.test
```

El comando carga `.env.academic` de forma predeterminada. Coloca `--env-file RUTA_PRIVADA` antes de `mfa-reset` si esa instalación usa otro archivo nativo.

En Docker, ejecuta desde la raíz sobre el contenedor API de la instalación.

```bash
docker compose --env-file .env.docker exec -T api python -m geocattle.account_maintenance mfa-reset --email administrador@example.test
```

Usa el correo real de la cuenta y el archivo privado de ese despliegue. La consola devuelve la misma confirmación general aunque no encuentre una cuenta activa. El restablecimiento cierra las sesiones, invalida desafíos y códigos de recuperación y queda auditado como `sistema/consola`. El titular conserva su contraseña. Al ingresarla, el sistema pide escanear el QR o introducir la clave manual y verificar un código nuevo antes de abrir la sesión.

## Integración MQTT y LoRaWAN

```bash
# Broker e ingestor con credenciales, persistencia y cola propia:
bash scripts/compose.sh --profile iot up -d

# Servidor de red local; no aprovisiona automáticamente el gateway ni nodos:
bash scripts/compose.sh --profile iot --profile lorawan up -d
```

ChirpStack se consulta en `http://localhost:8081` en simulación. Su cuenta administrativa inicial debe cambiarse antes de usar equipos reales. El servidor incluye Redis y base independiente. Broker en loopback 1884; si el gateway necesita conectarse desde LAN, configurar escucha y firewall de esa red y proteger el transporte. No dejar un broker anónimo accesible desde Internet.

El perfil de ejemplo utiliza AU915 canales 0–7 y 64 y tópicos `au915_0`; debe coincidir con LPS8N, nodos y backend del gateway. Las claves OTAA, firmware, tasa, potencia, máscara, codec y FPort se verifican en banco. Un perfil arrancado no es evidencia de interoperabilidad física. El ingestor recibe eventos de aplicación ChirpStack y el adaptador académico acepta el contrato JSON común. El tópico/codec exacto está documentado junto al código del ingestor.

El broker utiliza QoS1. La cola se conserva ante caída de PostgreSQL. El acuse de aplicación se emite tras confirmar escritura, no al recibir MQTT. Los mensajes inválidos quedan para revisión y no se atribuyen a un DIIO aproximado. Se conserva captura UTC y la asociación histórica.

## Reglas, cambios y atención

Guardar geocerca conserva versión y autor; una edición con versión obsoleta retorna conflicto. Una reasignación explícita cierra el intervalo anterior; la telemetría tardía consulta la vigencia de captura.

El intervalo activo se modifica sólo después de recibir la versión aplicada por el nodo. El despacho MQTT de configuración se habilita explícitamente con `CONFIG_DOWNLINK_ENABLED`, `CONFIG_CODEC_VALIDATED`, `CHIRPSTACK_APPLICATION_ID` y `CONFIG_FPORT` cuando el codec esté verificado. Enviado identifica entrega a la cola de red, y no aplicación por hardware; ésta exige una versión confirmada en telemetría. Sin downlink/confirmación real, la solicitud permanece pendiente y luego requiere revisión al vencer. Las reglas preventivas no habilitan diagnóstico. Los umbrales de demo son sintéticos: validar contacto térmico, algoritmo/ventana/línea base individual, tensión y tolerancia GNSS antes de aplicarlos al ganado.

Reconocer una alerta registra que fue vista. Revisar y concluir registran trabajo humano. La condición permanece activa hasta recibir evidencia de recuperación; una lectura inválida no prueba retorno. Los fallos de avisos externos preservan la alerta local.

Sin proveedor configurado, el worker registra el canal como deshabilitado y conserva su intento y el evento local. Un webhook opcional se configura por operador, con destino HTTPS autorizado y sin activar proveedores reales durante pruebas. Cada intento conserva resultado y referencia; aceptación HTTP no significa que una persona leyó el aviso. Para reintentos sin duplicación externa, el proveedor debe admitir la clave de idempotencia que envía el worker.

## Respaldo y recuperación

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh backups/geocattle-AAAAmmddTHHMMSSZ.dump
```

El respaldo PostgreSQL se guarda en formato custom con permisos restringidos. La restauración crea una base de ensayo con nombre distinto; nunca sobrescribe la base activa. Revisar conteos reales de DIIO, asociaciones, geocercas, telemetría, eventos y auditorías. Guardar una copia fuera del equipo y comprobar periódicamente su recuperación. Respaldo diario y retención se acuerdan con el productor; estos scripts no configuran por sí solos una tarea diaria.

RTO de dos horas y RPO de 24 horas son metas del informe. Registrar tiempos medidos desde incidente, copia disponible y restauración validada. No se presentan como SLA logrado por generar un archivo.

No eliminar observaciones sin política aprobada. La preserie propone 30 días de alta resolución y consulta al productor antes de borrar. Los registros inmutables y auditoría requieren un procedimiento de retención/migración explícito.

### Compartir una copia del prototipo

Desde la raíz de GeoCattle en el Windows de origen, con PostgreSQL del prototipo en ejecución:

```powershell
.\.venv\Scripts\python.exe scripts/compartir_base.py exportar --verificar
```

El comando toma una instantánea de solo lectura. La opción `--verificar` restaura la copia en otra base del servidor, compara conteos, identidades y factores MFA con la instantánea y elimina la base temporal. El directorio fechado de `.runtime/compartir/` contiene `geocattle.dump`, `geocattle.sha256` y `LEEME.md`. Las filas de métricas HTTP quedan fuera por defecto. Usa `--incluir-metricas` si la prueba las necesita.

Comprime los tres archivos juntos para enviarlos por un canal privado con acceso limitado al destinatario. El archivo contiene datos personales, historiales, hashes de contraseñas y datos cifrados de MFA. Mantén la copia y la configuración privada fuera de Git y de canales públicos. Las colas SQLite de captura y los `.env` quedan en el equipo de origen. Comparte la contraseña de acceso por un canal privado separado del archivo.

#### Preparar la instalación del destinatario

Usa la misma versión de GeoCattle que el origen o una más reciente. La copia sustituye los datos de desarrollo del destinatario. El importador comprueba el SHA-256, respalda la base existente en `.runtime/backups/`, restaura en una base vacía del mismo servidor y aplica las migraciones y los permisos con la configuración privada del destino. Activa la base preparada después de esas comprobaciones. Si la copia requiere una migración que falta en el código local, actualiza el repositorio y vuelve a importar. Mantén el entorno en desarrollo con `SIMULATION_ENABLED=false`.

**Windows nativo.** Completa la [instalación desde cero](../README.md) hasta inicializar el clúster PostgreSQL/PostGIS. Detén el prototipo activo y cualquier captura iniciada aparte. Desde la raíz, con los archivos extraídos en `.runtime/compartir/recibido/`, ejecuta:

```powershell
.\Detener-Prototipo.ps1
.\.venv\Scripts\python.exe scripts/compartir_base.py importar .runtime/compartir/recibido/geocattle.dump --destino nativo
```

El importador inicia solo PostgreSQL si hace falta. Cuando termine, abre `Abrir-GeoCattle.cmd` y entra en `http://localhost:8084`.

**Docker en Linux.** Detén la captura del anfitrión si estaba activa para ese destino. Desde la raíz, con los archivos extraídos en `.runtime/compartir/recibido/`, ejecuta:

```bash
python3 scripts/docker_project.py prepare --environment development
python3 scripts/docker_project.py stop --environment development
python3 scripts/compartir_base.py importar .runtime/compartir/recibido/geocattle.dump --destino docker
python3 scripts/docker_project.py start --environment development
```

En Docker para Windows, usa `py -3` en lugar de `python3`. Si el stack usaba perfiles, incluye los mismos `--profile` al detenerlo. El arranque anterior conserva las cuentas importadas y muestra el puerto de `.env.docker` (`8086` en una configuración nueva o `8084` si ya se usaba `Abrir-GeoCattle.sh`).

#### Iniciar sesión y conservar TOTP

Inicia una sesión nueva con el correo y la contraseña de origen. La verificación Argon2 usa el hash guardado en la base y funciona con los secretos propios del destinatario.

- Para seguir usando el TOTP de origen, configura `MFA_ENCRYPTION_KEY` en el archivo privado del destino (`.env.academic` o `.env.docker`) antes de iniciar la aplicación. Usa el valor de `MFA_ENCRYPTION_KEY` del origen si está definido, o el valor de `SESSION_SECRET` del origen si se usaba como clave de cifrado. Comparte ese valor aparte por un canal privado. Conserva el `SESSION_SECRET` del destino y usa un código vigente del autenticador original. Los códigos de recuperación de origen están vinculados a su `SESSION_SECRET`.
- Para usar un autenticador propio en la copia, aplica el [restablecimiento de TOTP por consola](#restablecer-el-autenticador-por-consola) en el destino y completa la inscripción al entrar. La contraseña se conserva. El restablecimiento afecta solo la copia importada y permite mantener privadas las claves de origen.

## Revisión de operación

- Diaria: módulos ausentes, frescura, eventos, avisos, disco, energía y última copia.
- Semanal: montaje, correa, caja, antena y falsos avisos; registrar mantenimiento.
- Recarga: retirar collar, revisar batería y montaje, cargar con circuito validado y registrar tensión/responsable.
- Nueva versión: respaldo, revisión, migración, regresión, evidencia y reversión.
- Retiro: deshabilitar explícitamente dispositivo, cerrar asignaciones según procedimiento, revocar claves y registrar disposición.

Ante una falla, registrar hora/activo/síntoma/severidad/responsable. Conservar origen legible, restablecer versión conocida, restaurar a una instancia distinta y validar integridad antes de reemplazar el servicio. Reinyectar colas con idempotencia. No completar períodos sin observación con valores supuestos.
