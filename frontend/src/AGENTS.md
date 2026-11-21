# Interfaz React

## Propósito y alcance

`App.tsx` organiza la navegación y el contexto. `FarmSelector.tsx` provee el selector accesible de predio. `V3*.tsx` reúne flujos por rol y `Pages*.tsx` contiene pantallas de gestión. `Map.tsx`, `GeofenceForm.tsx` y `geofenceDraft.ts` componen el mapa y la edición de geocercas. `HardwarePage.tsx` y `TelemetryView.tsx` muestran recepción e historial.

## Contratos locales

- Reutiliza `api.ts` al llamar al backend y actualiza `types.ts` o `v3types.ts` junto con el contrato. Conserva el contexto del predio al cambiar consultas o acciones y apóyate en la autorización del backend.
- El formulario sanitario obtiene las reglas de productos y vías de `/v3/health/product-policies` y adapta los campos al evento. Al corregir un evento que admite productos, conserva los datos ya registrados, incluidos el registro del producto, el lote y el fundamento del resguardo. Si una vacuna histórica figura con vía oral, deja su selector vacío para que se indique la vía usada. La agenda de vacunación y antibiótico ofrece eventos efectivos compatibles y conserva el tipo planificado al completar la atención.
- **Reportes del rebaño** (`#reports`) consulta y descarga registros con los filtros aplicados a la vista previa. La ficha sanitaria puede abrir esa página con el bovino preseleccionado mediante `#reports?animal=<id>`.
- Para dueño y administrador, **Reportes del rebaño** abre los totales del predio y ofrece alertas agrupadas y rankings con evidencia de cobertura. La descarga conserva el período, la agrupación y el tipo de alerta de la vista previa.
- En geocercas, conserva la sincronización entre vértices y coordenadas y la función de deshacer. En telemetría, conserva la diferencia entre una posición ausente, un dato previo y una lectura nueva. [Geocercas y alertas](../../docs/CORRECCIONES_GEOCERCAS_ALERTAS_2026-10-29.md) · [Telemetría](../../docs/VISUALIZACION_TELEMETRIA.md)
- Estructura y navegación de la barra lateral:
  - La barra lateral ocupa la altura completa del viewport (`100vh`) sin scroll general. La cabecera (marca y selector de predio) y el pie (estado y usuario) permanecen fijos.
  - Solo la navegación central (`.sidebar-nav`) es desplazable, utilizando scrollbar discreto adaptado a la paleta verde.
  - El selector de predio (`FarmSelector.tsx`) es personalizado y accesible (soporte de teclado con flechas, Escape, Enter, tab, foco, cierre al hacer clic fuera, truncamiento de nombres largos y estado de carga durante `/auth/context`), coherente con la paleta verde del prototipo sin depender de menús nativos del navegador. La opción "Panel global" se reserva a administradores.
  - El engranaje de perfil se ubica a la izquierda de «Cerrar sesión» y abre `#profile` (`ProfilePage`) para datos y seguridad. «Reglas del predio» (`#settings`) se encuentra en «Gestión del predio» para los roles autorizados.
  - Alertas y avisos en cabecera: "Alertas y atención" (`#events`) se retira de la lista del sidebar y se ubica como campanilla en la cabecera con contador de eventos activos (`overview.summary.active_events`). "Avisos personales" (`#notices`) se ubica contiguo con icono distinguible (`Inbox`) y texto accesible.
  - Los avisos muestran el contador del predio activo y pueden enlazar a `#changes?request=<id>`. El detalle aplica los permisos de la API. "Mis solicitudes a soporte" (`#support`) acompaña a la cuenta en cualquier contexto y "Solicitudes de soporte" (`#support-admin`) se abre desde el panel global.
  - `SidebarNavigation` agrupa las páginas autorizadas en Rebaño y salud, Territorio, Dispositivos, Gestión del predio y Administración. Los paneles de inicio y los destinos que quedan solos en su grupo se muestran directamente. El submenú de la página activa se abre al navegar por hash, también con Atrás y Adelante.
  - `events`, `notices` y `profile` conservan su registro en `allNavigation`, `allowed`, breadcrumbs y la navegación directa por hash.

## Verificación

Ejecuta la suite y el build descritos en [frontend](../AGENTS.md). Para cambios de permisos o mapas, usa los recorridos de [verificación](../../docs/VERIFICACION.md) con datos de QA.
