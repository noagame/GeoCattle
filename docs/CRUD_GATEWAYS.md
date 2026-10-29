# Gestión de gateways por predio

Dueño y administrador con predio seleccionado pueden registrar, consultar,
editar y archivar gateways desde **Gateways instalados**. El dueño solo accede
a sus predios autorizados. El servidor rechaza escrituras sin contexto y
accesos a gateways de otro predio. Los demás roles mantienen lectura autorizada.

## Identidad, ubicación e historial

- El UUID interno lo genera el servidor; el EUI físico consta de 16 caracteres
  hexadecimales y se normaliza a minúsculas. UUID, EUI y predio son inmutables.
- Los registros nuevos requieren nombre y coordenadas WGS84 finitas. Los
  registros anteriores sin ubicación siguen consultables y pueden completarse.
- El formulario sincroniza campos y un único marcador G arrastrable. Activar
  la selección permite reemplazar su ubicación con un clic. Guardar confirma
  los cambios; cancelar y descartar conserva los valores persistidos.
- Leaflet recibe `[latitud, longitud]`; PostGIS almacena `[longitud, latitud]`.
- Instalado, Mantenimiento y Retirado son estados administrativos. Archivado
  es una baja lógica independiente, con confirmación, fecha y actor. El listado
  operativo y el mapa general excluyen archivados; el filtro del inventario
  permite consultar su detalle y recepciones. El EUI permanece reservado.
- Registrar o mover un marcador no provisiona hardware ni acredita conexión.
  Se muestra la última recepción disponible sin afirmar conectividad actual.

## Contrato HTTP

Rutas bajo `/api/v1/v3`, con sesión y contexto de predio existentes:

| Método y ruta | Solicitud / resultado |
| --- | --- |
| `GET /gateways` | Inventario operativo; `include_archived=true` incluye bajas. |
| `GET /gateways/{uuid}` | Detalle canónico, `version` y `reception_count`. |
| `GET /gateways/{uuid}/receptions` | Historial paginado: `limit` 1–200 (50 por defecto), `offset` >= 0. |
| `POST /gateways` | `name`, `gateway_eui`, `latitude`, `longitude` obligatorios; responde 201. |
| `PATCH /gateways/{uuid}` | `expected_version` obligatorio; nombre, estado y par de coordenadas opcionales. |
| `DELETE /gateways/{uuid}` | JSON `{"expected_version": 1, "confirm": true}`; archiva y responde 200. |

Los clientes anteriores deben enviar ubicación al crear y `expected_version`
al modificar. No se aceptan cambios del EUI ni coordenadas parciales/nulas.
Los conflictos de versión, EUI duplicado o edición de archivados responden 409;
los datos inválidos, 422. El cliente debe volver a abrir el formulario ante un
conflicto. Repetir un archivado ya realizado es idempotente. Un PATCH sin cambios
no incrementa versión ni genera una auditoría ficticia.

Actualización y archivado bloquean la fila y guardan cambios y auditoría en una
misma transacción. La auditoría conserva actor, predio, fecha y valores antes y
después. `version` solo cambia por gestión del inventario, no por recepciones.

## Migración y captura

Aplicar `python -m geocattle.migrate` antes del frontend/API nuevos. La migración
**005_gateway_management.sql** añade archivo, versión, índices, validación de
ubicación e identidad inmutable; no modifica migraciones anteriores ni elimina
registros. El ejecutor versionado evita reaplicarla. Una ubicación previa fuera
de WGS84 provoca fallo transaccional y requiere revisar el dato antes de migrar.
Hacer respaldo y verificar primero en una base PostGIS aislada.

La captura conserva sus payloads, EUI, UUID y recepción originales. Mover o
archivar no reescribe telemetría ni recepciones. Si sigue llegando evidencia de
un gateway archivado, la ingestión puede conservarla y actualizar `last_seen_at`
sin reactivarlo en el inventario operativo. La baja no envía comandos físicos.

Se inspeccionó `origin/dev/hardware-captura` en `3574754`, cuyo WIP documenta
seis fallos de lotes. No se integra esa rama ni se cambia su protocolo en este
trabajo. El PR hacia `develop` debe revisarse junto al responsable de captura;
los checks de software no sustituyen pruebas con placas reales.

## Validación del 29 de octubre de 2026

- Base de trabajo `dev/software`, sincronizada con `origin/dev/software` y
  `develop`, ambos en `eac8ecb` al comenzar.
- PostgreSQL/PostGIS QA: 143 pruebas del backend aprobadas. Cubren permisos,
  aislamiento, validaciones, concurrencia por versión, legado sin ubicación,
  auditoría, archivado y preservación exacta de recepciones/telemetría.
- Migración en copia aislada del respaldo: registros preservados y segunda
  ejecución idempotente, incluido un gateway antiguo sin ubicación.
- `npm test`: 4 pruebas de geocercas y 3 de coordenadas de gateways aprobadas.
- `npm run build`: compilación TypeScript/Vite correcta (aviso de tamaño de
  bundle existente).
- Check de captura: 63 pruebas aprobadas; reglas de dominio: 7 aprobadas.
- Navegador con cuentas QA de dueño y administrador (MFA): alta, clic en mapa,
  arrastre, edición manual, guardar/reabrir, cancelar confirmación y archivado.
  Se verificó el historial conservado y la exclusión del mapa general.

Los respaldos, cuentas QA, registros de ejecución y capturas quedan fuera de Git.
El workflow ejecuta también `geocattle-backend-postgis` en cada subida y PR:
migra una base PostGIS temporal desde cero, repite las migraciones y ejecuta
`python -m pytest backend/tests -q`. Así, las pruebas de gateways y permisos
forman parte de la CI además de la verificación local.
La integración del PR y la promoción `develop` → `main` requieren revisión y
aprobación explícita.
