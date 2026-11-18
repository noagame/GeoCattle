# Interfaz React

## Propósito y alcance

`App.tsx` organiza la navegación y el contexto. `V3*.tsx` reúne flujos por rol y `Pages*.tsx` contiene pantallas de gestión. `Map.tsx`, `GeofenceForm.tsx` y `geofenceDraft.ts` componen el mapa y la edición de geocercas. `HardwarePage.tsx` y `TelemetryView.tsx` muestran recepción e historial.

## Contratos locales

- Reutiliza `api.ts` al llamar al backend y actualiza `types.ts` o `v3types.ts` junto con el contrato. Conserva el contexto del predio al cambiar consultas o acciones y apóyate en la autorización del backend.
- En geocercas, conserva la sincronización entre vértices y coordenadas y la función de deshacer. En telemetría, conserva la diferencia entre una posición ausente, un dato previo y una lectura nueva. [Geocercas y alertas](../../docs/CORRECCIONES_GEOCERCAS_ALERTAS_2026-10-29.md) · [Telemetría](../../docs/VISUALIZACION_TELEMETRIA.md)

## Verificación

Ejecuta la suite y el build descritos en [frontend](../AGENTS.md). Para cambios de permisos o mapas, usa los recorridos de [verificación](../../docs/VERIFICACION.md) con datos de QA.
