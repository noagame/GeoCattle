# Plan del modo espejo: PC del campo como sistema principal y web como espejo en vivo

Estado: **aprobado e implementado el 2026-11-26**. El ensayo con dos instalaciones locales enlazadas por el túnel y la réplica pasó 12 de 12 comprobaciones; queda la prueba con Cloudflare real y hardware en terreno. Las decisiones D1 a D6 quedaron aprobadas tal como se recomiendan. En D5 la T3 inalámbrica se retira: la única receptora es la T3 base por USB.

## 1. Objetivo

- El PC del predio sigue siendo el sistema principal. Recibe las lecturas por USB desde la T3 base, calcula las alertas al instante y funciona sin internet.
- El servidor web es un **espejo casi en vivo** del PC. Cuando hay conexión muestra mapa, temperatura, alertas y fichas con unos segundos de atraso. Cuando no la hay, muestra lo último recibido y se pone al día solo.
- En la web, cada rol tiene estos permisos:
  - **Administrador (soporte):** actúa sin aprobación del dueño. Sus órdenes bajan al PC y se aplican solas.
  - **Veterinario:** crea solicitudes y borradores. El dueño las aprueba en el PC.
  - **Dueño y demás:** consultan los datos del predio.
  - **Todas las cuentas:** pueden enviar solicitudes personales de soporte y consultar su estado.
- Nada se pisa entre el PC y la web. Cada dato tiene un solo lugar donde se escribe, cada envío tiene un identificador aleatorio (UUID) y cada registro editable tiene versión.

## 2. Lo que ya existe y se reutiliza

| Pieza actual | Uso en el modo espejo |
|---|---|
| Todas las tablas usan clave primaria UUID, sin secuencias. | Replicar sin choques de identificadores. Las solicitudes nacidas en la web conservan su UUID al bajar. |
| PostgreSQL 16 en el PC (nativo, `.runtime/postgres16`) y en el servidor (`postgis/postgis:16-3.4`). | Replicación lógica nativa de PostgreSQL, sin programar un sincronizador tabla por tabla. |
| `change_requests`, `change_decisions` y `change_applications` con aprobación del dueño, autoría y auditoría (`/v3/changes`, `/v3/changes/{id}/decision`). | Las solicitudes del veterinario hechas en la web se convierten en solicitudes pendientes del PC. |
| `expected_version` en la ficha del bovino y claves de idempotencia por usuario. | Detectar conflictos y evitar dobles envíos al reintentar. |
| `useData(path, interval)` en `frontend/src/api.ts`, que recarga cada 5 a 30 s. | La web se actualiza sola; no hace falta WebSocket. |
| Cloudflare Tunnel en `compose.cloudflare.yaml`. | Mismo túnel para la web, el canal de réplica y el soporte remoto. |
| Captura USB con cola durable. | Única entrada de lecturas; la T3 inalámbrica no se usa (D5). |

## 3. Arquitectura

```text
 CAMPO (PC, sistema principal)                         SERVIDOR (espejo)
 ┌───────────────────────────────┐                    ┌──────────────────────────────────┐
 │ T3 base USB ─► captura ─► API │                    │ cloudflared ◄── navegador (web)  │
 │                               │                    │      │                           │
 │ worker: alertas, avisos       │                    │      ▼                           │
 │ PostgreSQL 16 (publicación) ──┼─ réplica lógica ──►│ PostgreSQL 16 (suscripción)      │
 │                               │  por túnel SSH     │   tablas espejo: solo lectura    │
 │ sync del espejo (worker) ◄────┼─ HTTPS: bandeja ───│   tablas propias: sesiones, cola │
 │   aplica órdenes y solicitudes│                    │ API en MIRROR_MODE=replica       │
 │ ssh -R (sale del PC) ─────────┼─ Cloudflare ──────►│ contenedor "espejo-ssh"          │
 └───────────────────────────────┘                    └──────────────────────────────────┘
```

**Subida (PC → web): replicación lógica de PostgreSQL**
- El PC publica las tablas del dominio y el servidor las recibe.
- Llegan en orden de commit, a los pocos segundos.
- Si se corta internet, el PC retiene los cambios (con un tope de disco) y los entrega al volver.

**Bajada (web → PC): bandeja HTTPS**
- El worker del PC consulta la bandeja del servidor cada 10 s cuando hay conexión.
- Trae las órdenes del administrador, las solicitudes y borradores del veterinario y las solicitudes personales de soporte. Aplica las reglas de cada operación y confirma el resultado.
- El resultado sube por la réplica.

**Conexión**
- La réplica necesita que el servidor llegue a la base del PC.
- El PC abre un túnel SSH inverso hacia un contenedor dedicado del servidor, a través de Cloudflare. La conexión sale del PC, así que no hay que abrir puertos en el campo.
- El mismo túnel publica la web del PC para soporte remoto, protegida por Cloudflare Access.

### Por qué esta forma

- **Programar la réplica en la aplicación** exigiría capturar cambios en unas 55 tablas y reaplicarlos desde la API. Eso choca con los triggers de inmutabilidad y validación, por ejemplo `telemetry_immutable`, `validate_decision` y `validate_assignment_interval_v3`. En cambio, PostgreSQL aplica la réplica lógica sin disparar esos triggers en el espejo y conserva el orden.
- **Bajar con HTTPS y no con una segunda réplica** tiene tres ventajas:
  - Cada orden pasa por los mismos endpoints, permisos y validaciones del PC.
  - Se audita como una acción normal.
  - El PC decide qué aceptar.

## 4. Clasificación de tablas

Cada tabla queda en una sola clase. Una prueba nueva hará fallar CI si una migración agrega una tabla sin clasificar. La lista vive en `backend/geocattle/mirror_tables.py`.

| Clase | Tablas | Regla |
|---|---|---|
| **Espejo** (se escribe solo en el PC y se replica) | farms, users, owner_accounts, platform_admins, roles, permissions, role_permissions, farm_memberships, trust_grants, mfa_factors, sectors, geofences, geofence_sectors, pasture_assignments, animals, animal_holdings, animal_states, animal_measurements, animal_reports, devices, device_configs, assignments, telemetry, telemetry_receptions, events, event_actions, rule_settings, notifications, notification_attempts, maintenance, health_events, health_treatments, health_schedules, change_requests, change_decisions, change_applications, sag_movements, movement_animals, movement_status_events, features, farm_features, gateways, gateway_candidates, gateway_bus_receipts, device_candidates, device_candidate_captures, receiver_status, support_requests, audit_log, schema_migrations*, change_drafts (nueva), mirror_heartbeat (nueva) | En el servidor, el usuario de la API solo tiene `SELECT`. |
| **Solo PC** (no se replica) | login_sessions, auth_challenges, account_tokens, mfa_recovery_codes, invitations, invitation_mail, request_metrics | Sesiones, códigos y correos del campo. |
| **Solo servidor** (nuevas, no se replican) | mirror_outbox (órdenes y solicitudes web), mirror_totp_use, mirror_audit_log, mirror_notification_reads, más login_sessions, auth_challenges y request_metrics del servidor | El servidor escribe aquí y en nada más. |

\* `schema_migrations` no se replica. Cada lado aplica sus migraciones, y la herramienta compara las versiones antes de replicar.

A revisar al implementar:
- `mfa_recovery_codes`: hoy queda solo en el PC, así que los códigos de recuperación solo sirven en el PC.
- `invitations`: las invitaciones se crean y se envían desde el PC.

## 5. Permisos en la web (`MIRROR_MODE=replica`)

| Rol | Lectura | Escritura en la web |
|---|---|---|
| Administrador de plataforma | Todo | Lista permitida del apartado de admin y de `/v3/changes`. Se encola como **orden de administrador**: la API responde `202` con el UUID y el PC la aplica sin aprobación. |
| Veterinario | Su predio | `POST /v3/changes` (animal_profile, health_record, health_schedule) y borradores. Se encola como **solicitud remota** y en el PC queda **pendiente** del dueño, aunque en el PC el veterinario aplique directo. |
| Dueño, operador, trabajador, visor | Su predio | Marca avisos como leídos, que quedan guardados en el servidor. |

Cualquier cuenta autenticada puede encolar `POST /api/v1/auth/support-requests`. El caso personal se escribe en el PC y vuelve por la réplica.

- **Inicio de sesión:** las cuentas vienen del PC, con la misma contraseña y el mismo TOTP. La sesión, el desafío MFA y el contador anti-reuso de TOTP se guardan en tablas del servidor.
- **Doble defensa:**
  - El middleware de la API rechaza toda escritura fuera de la lista.
  - La base del servidor solo da `SELECT` sobre las tablas espejo, así que un error de código falla visiblemente y no rompe la réplica.

## 6. Bajada de órdenes y solicitudes

Cada envío de la web es una fila en `mirror_outbox` con estos campos:
- `id` (UUID aleatorio), `kind` (`admin_order`, `remote_change`, `draft_revision`, `support_request`) y `actor_id`.
- `method`, `path` y `body` dentro de la lista permitida.
- `created_at` y `status`, que pasa por `queued → delivered`. El estado final (`applied`, `pending_owner`, `rejected`, `conflict` o `failed`) llega por la réplica en `mirror_inbox_results`.

1. El worker del PC llama a `GET /api/v1/mirror/inbox` por HTTPS, con `X-Mirror-Key` y, si se usa, el token de servicio de Cloudflare Access.
2. Por cada fila, comprueba en su base que el actor existe y está activo. Exige rol de administrador para órdenes y membresía veterinaria vigente para solicitudes y borradores de predio.
3. Reproduce la operación dentro de la misma API del PC, como llamada interna con ese actor:
   - **orden de admin:** se aplica directo y se audita como `remote_admin`;
   - **solicitud del veterinario:** `submit()` recibe `remote=True`, que obliga a dejarla pendiente y avisa al dueño. La solicitud usa el UUID del envío como `idempotency_key`;
   - **solicitud de soporte:** el caso se crea con la cuenta autora y el UUID del envío como folio. El mismo envío puede reentregarse sin duplicar el caso.
4. Guarda el resultado en `mirror_inbox_results`, que sube por la réplica junto con los registros creados, y la web muestra el estado: "en cola para el campo", "pendiente del dueño", "aplicada" o "rechazada: motivo".
5. **Interruptores en el PC:**
   - `MIRROR_REMOTE_ADMIN=false` desactiva las órdenes remotas de admin;
   - `MIRROR_REMOTE_CHANGES=false` desactiva las solicitudes veterinarias, los borradores y las solicitudes personales de soporte.

## 7. Borradores: empezar en terreno y seguir en línea

- **Tabla nueva `change_drafts`:** id UUID, farm_id, author_id, action, animal_id, payload, version, status (`draft`, `submitted`, `discarded`) y updated_at. Vive en el PC y se replica.
- **En el PC:** el veterinario guarda un borrador de atención sin enviarlo. Cada guardado sube `version`.
- **En la web:** ve sus borradores replicados y sigue editando. Cada guardado web crea un `draft_revision` en la bandeja con `base_version`, y la web muestra la última revisión encolada encima del borrador replicado. Así se puede seguir trabajando aunque el PC esté sin conexión.
- **Al aplicar en el PC:**
  - si `base_version` coincide, se actualiza el borrador;
  - si alguien lo cambió en el PC entretanto, no se pisa: se guarda como borrador hermano "conflicto" y el veterinario elige cuál enviar.
- **Enviar:** convierte el borrador en una solicitud con el mismo UUID, de modo que nunca se duplica.

## 8. Espejo en vivo y frescura

- **Pulso del PC:** el worker del PC actualiza `mirror_heartbeat` cada 15 s con la hora, la versión del esquema y la cola pendiente. La fila se replica.
- **Banner de la web:** "Datos del campo al 14:32:10 (hace 8 s)" o "Campo sin conexión desde 13:05; mostrando lo último recibido".
- **Ritmo de recarga:** las vistas en vivo (mapa, resumen de hardware, alertas) ya recargan cada 5 a 15 s. En modo espejo se mantienen los intervalos actuales.
- **Atraso en el servidor:** `GET /api/v1/mirror/status` entrega el atraso de la réplica (`pg_stat_subscription`) para el panel del administrador.

## 9. Infraestructura y operación

**PC (Windows nativo)**
- `scripts/mirror.py pc-setup` deja la base del PC lista para publicar:
  - activa `wal_level=logical` y `max_slot_wal_keep_size=2GB` en el arranque de `prototype_windows.py`;
  - crea el rol `geocattle_replica`, con `REPLICATION` y `SELECT` sobre las tablas espejo, y la publicación `geocattle_espejo`.
- `scripts/mirror.py tunnel`: túnel `ssh -N -R` con `cloudflared access ssh` como ProxyCommand, reconexión automática y tarea programada de Windows. Publica la base del PC en `espejo-ssh:15432` y su web en `espejo-ssh:18084`.

**Servidor (Debian 12 o 13)**
- **Perfil Compose `mirror`:**
  - contenedor `espejo-ssh`: sshd mínimo que acepta solo reenvío de los puertos 15432 y 18084, con la clave pública del PC, sin shell ni pty;
  - API y worker con `MIRROR_MODE=replica`: el worker no calcula alertas, no envía avisos ni correos y no despacha configuraciones.
- **`scripts/mirror.py subscribe`:** compara migraciones, vacía las tablas espejo del servidor y crea la suscripción `copy_data=true, disable_on_error=true`.
- **Otros comandos:** `status` (atraso, slot, última orden aplicada) y `resync` (si el slot se perdió por un corte largo).
- **Cloudflare:** se agregan dos hostnames al túnel existente, `espejo-ssh.<dominio>` (SSH) y `soporte.<dominio>` (web del PC). Los dos van tras Cloudflare Access, con un token de servicio para el PC y los correos de los administradores para soporte.
- **Ingesta directa en el servidor:** desactivada en modo espejo, porque duplicaría lecturas que ya llegan por la réplica.

**Actualizaciones**
- La réplica no copia cambios de esquema.
- `mirror.py upgrade` aplica las migraciones primero en el servidor y luego en el PC, y después refresca la publicación y la suscripción.
- Se respalda antes en ambos lados (contrato de `docs/OPERACION.md`).

## 10. Decisiones que necesito que apruebes

| # | Decisión | Recomendación |
|---|---|---|
| D1 | Entorno del PC. Hoy los predios del PC son `development` y la web de producción solo muestra predios `production`. | Mantener el PC en `development`, para no perder las alertas de temperatura del prototipo ni exigir HTTPS local. El servidor espejo usa `MIRROR_SOURCE_ENVIRONMENT=development` solo para la visibilidad, y conserva todas las exigencias de seguridad de producción. |
| D2 | Qué puede hacer el admin en remoto. | El apartado de admin (dueños, usuarios, soporte, KPI) y `/v3/changes`. Gestión de collares y gateways solo por soporte remoto a la web del PC, porque requiere USB. |
| D3 | Acceso del dueño a la web. | Lectura de los datos del predio. Las solicitudes personales de soporte están disponibles para todas las cuentas. |
| D4 | Acciones del veterinario en la web. | animal_profile, health_record, health_schedule y borradores; todo pendiente del dueño. |
| D5 | T3 inalámbrica. | Retirada: solo la T3 base por USB. |
| D6 | Corte largo de internet. | Retener hasta 2 GB de cambios en el PC. Si se supera, `mirror.py resync` vuelve a copiar todo. |

## 11. Etapas, reparto y criterios de aceptación

Orquestación: yo (Claude) coordino, defino los contratos y reviso cada entrega. Codex implementa las tareas marcadas y yo integro y verifico. Cada etapa termina con pruebas en verde y una demostración en el servidor local.

| Etapa | Contenido | Quién | Aceptación |
|---|---|---|---|
| E0 Contratos | `mirror_tables.py`, migración `014_mirror_mode.sql` (tablas del servidor, `change_drafts`, `mirror_heartbeat`), contrato de la bandeja en `CONTRATO_API.md`. | Claude | Prueba que falla si hay una tabla sin clasificar. La migración pasa sobre una copia con datos. |
| E1 Réplica | `scripts/mirror.py` (pc-setup, tunnel, subscribe, status, resync, upgrade), perfil Compose `mirror` y contenedor `espejo-ssh`. | Claude | Dos stacks locales (PC simulado y servidor). Una lectura aparece en el espejo en menos de 10 s. Tras cortar el túnel 10 min, se pone al día sin pérdida ni duplicados. |
| E2 API espejo | `MIRROR_MODE`, middleware de escrituras, permisos de la base, sesión, TOTP y auditoría en tablas del servidor, worker sin alertas, visibilidad D1. | Codex | Cada GET responde en el espejo con permisos de solo lectura. Toda escritura no permitida da 403. El inicio de sesión con TOTP funciona en el espejo. |
| E3 Bandeja | Outbox, `/api/v1/mirror/inbox`, sync del worker del PC, reproducción interna con actor, `remote=True` en `submit()`, interruptores. | Codex (Claude revisa seguridad) | Una orden de admin se aplica sola. Una solicitud del veterinario queda pendiente y el dueño la aprueba en el PC, con autor y aprobador conservados. Los reintentos no duplican. |
| E4 Interfaz | Banner de frescura, botones según modo y rol, respuestas `202` con estado y "Mis envíos". | Codex | Pruebas de frontend y revisión visual con Playwright en los dos modos. |
| E5 Borradores | `change_drafts` en el PC, revisiones web y conflicto como borrador hermano. | Codex | Escenario: empezar en el PC, seguir en la web sin conexión con el PC y enviar. Un conflicto deja las dos versiones. |
| E6 Ensayo y paquete | Prueba de punta a punta con hardware (T3 base USB, gateway, collar), guía de despliegue, `empaquetar_despliegue.py --mirror`. | Claude | Guía ejecutada en limpio sobre los dos stacks locales. Paquete con SHA-256. |

E2 y E1 pueden avanzar en paralelo después de E0. E3 necesita E1 y E2, E4 necesita E2, y E5 necesita E3 y E4.

## 12. Cómo se sube al servidor de tu amigo (resumen, la guía final irá en `DESPLIEGUE_DEBIAN_CLOUDFLARE.md`)

1. **Necesitas:** acceso SSH por Cloudflare al servidor, acceso al panel de Cloudflare del dominio (o que tu amigo cree los hostnames), y Docker en Debian 13. Antes de instalar, confirmo `uname -m` (amd64 o arm64).
2. **Cloudflare:**
   - túnel con tres hostnames: `geocattle.<dominio>` → web, `espejo-ssh.<dominio>` → `espejo-ssh:22` y `soporte.<dominio>` → `espejo-ssh:18084`;
   - aplicación de Access para los dos últimos, con un token de servicio para el PC y los correos de los administradores.
3. **Servidor:**
   - subir el paquete;
   - `docker_project.py prepare --domain geocattle.<dominio> --mirror`, que genera `MIRROR_SYNC_KEY` y la configuración privada;
   - cargar el token del túnel;
   - arrancar con `--profile cloudflare --profile mirror` e instalar el temporizador de respaldos.
4. **PC:**
   - respaldar la base;
   - `mirror.py pc-setup`, que reinicia PostgreSQL con réplica lógica;
   - instalar cloudflared, crear la clave SSH del PC, autorizarla en el servidor y activar la tarea `mirror.py tunnel`.
5. **Servidor:** `mirror.py subscribe`. Desde ese momento, el espejo copia todo y sigue en vivo.
6. **Verificar:**
   - `mirror.py status` en los dos lados;
   - banner "hace N s" en la web;
   - una orden de admin y una solicitud de veterinario de prueba.
7. **Mantención:** `mirror.py upgrade` para nuevas versiones (servidor primero) y `mirror.py resync` tras un corte mayor al tope.

## 13. Riesgos y límites

- **La web va atrasada** respecto del campo, tanto como dure la falta de internet. Las alertas en tiempo real están garantizadas solo en el PC.
- **Disco del PC:** el slot de réplica retiene cambios mientras no hay conexión. El tope de 2 GB protege el disco; superarlo obliga a `resync`.
- **Un código TOTP** usado en el PC podría reutilizarse una vez en la web dentro de los mismos 30 s, porque los contadores anti-reuso son independientes. Es un riesgo bajo, y queda documentado.
- **Servidor comprometido:** podría encolar órdenes de admin. Mitigación: lista permitida de rutas, auditoría en el PC y `MIRROR_REMOTE_ADMIN=false` como interruptor del dueño.
- **Esquemas en ambos lados:** un cambio de esquema exige actualizar los dos lados con `mirror.py upgrade`. Mientras no se haga, la herramienta bloquea la réplica en lugar de dañar datos.
