# Configuración de parámetros desde Alertas y atención

Actualización: 24 de octubre de 2026.

## Acceso

El dueño selecciona su predio y abre **Alertas y atención → Configurar alertas**. El administrador dispone del mismo botón después de seleccionar un predio de soporte. Trabajador, veterinario y perfil de consulta no reciben controles de configuración; la API rechaza sus escrituras con 403. La atención de eventos mantiene sus permisos anteriores.

El formulario es el mismo en **Reglas del predio**. Ambos accesos consultan y guardan una única configuración por predio; no hay una copia independiente en cada panel.

## Parámetros disponibles

| Parámetro | Evaluación | Rango admitido |
|---|---|---|
| Batería baja | Tensión medida menor que el umbral, en mV; el formulario muestra también V | 0–20000 mV |
| Temperatura superficial elevada | Medición igual o mayor que el umbral; activación independiente | −60 a 100 °C; admite dejar umbral vacío si está desactivada |
| Actividad reducida | Promedio menor que el índice mínimo, con ventana completa y sin huecos de lecturas | Índice 0–1000000; ventana 1–1440 minutos |
| Cercanía al límite de geocerca | Animal dentro de su zona y distancia al borde menor o igual que el umbral | 0–1000 metros; requiere zona asignada y GPS válido |

Se corrigió el texto antiguo que describía la proximidad como distancia entre animales. La regla existente usa la distancia al borde de la geocerca; no se cambió su cálculo.

Temperatura y actividad conservan la validación preventiva del servidor. Cuando no están habilitadas para el entorno, se pueden guardar sus umbrales, pero sus interruptores de activación aparecen bloqueados con una explicación. No se ha declarado validación de campo mediante este ajuste.

Las reglas automáticas de vigencia de posición, ausencia de comunicación y dos posiciones exteriores consecutivas se explican al pie del formulario y mantienen su comportamiento. No son campos nuevos configurables en esta entrega.

## Guardado e historial

- **Guardar parámetros** se habilita al cambiar un valor. Se crea una nueva versión y una entrada de auditoría con valores anteriores, nuevos y autor.
- La configuración pertenece al predio autorizado de la sesión; no se puede enviar otro predio en el cuerpo para cambiarlo.
- Una versión obsoleta devuelve 409. El formulario conserva el borrador y ofrece recargar la versión vigente; no sobrescribe silenciosamente otro cambio.
- Las nuevas reglas se evalúan con las próximas lecturas. Guardar o desactivar una regla no elimina eventos anteriores ni concluye su atención humana.
- Los datos y umbrales del predio operativo se conservaron. Los valores de ejemplo de las capturas se guardaron únicamente en el predio QA aislado.

## Contrato adicional de API

GET y PUT `/api/v1/settings` devuelven los campos habituales y:

```json
{
  "capabilities": {
    "can_edit": true,
    "environment": "development",
    "preventive_rules_validated": false,
    "preventive_rules_allowed": false
  }
}
```

La metadata es de lectura y no se envía en PUT. Las escrituras siguen usando `SettingsIn`, `expected_version`, CSRF y autorización de dueño/administrador. La auditoría conserva solo los parámetros efectivos, sin esa metadata. Administrador sin predio seleccionado recibe 409 y reglas inexistentes reciben 503.

## Verificación

- 109 pruebas de backend correctas, incluidas 14 verificaciones adicionales sobre configuración: roles, aislamiento, versiones, auditoría y activación preventiva.
- TypeScript y compilación Vite correctos.
- Registro automatizado: `.runtime/review/alert-settings-tests-2026-10-24.txt`.
- Las comprobaciones visuales y los cambios de prueba se realizan en `geocattle_review_20261023`, separada de la base operativa.

### Comprobación visual en base aislada

- Dueño: apertura desde Alertas, edición y guardado; valores conservados al reabrir.
- Administrador: acceso después de MFA y selección de predio; edición y guardado correctos.
- Trabajador y veterinario: consulta de eventos disponible, sin botón de configuración.
- Dos sesiones: respuesta 409 al guardar una versión antigua, borrador conservado y recarga explícita; guardado posterior correcto.
- La API temporal de QA se cerró al terminar, sin detener PostgreSQL, la API operativa ni COM5.

Capturas con datos ficticios de QA:

- [Formulario del dueño](evidencias/alertas-2026-10-24/GeoCattle-configurar-alertas-dueno-QA.png).
- [Formulario del administrador](evidencias/alertas-2026-10-24/GeoCattle-configurar-alertas-admin-QA.png).
- [Guardado y reglas automáticas](evidencias/alertas-2026-10-24/GeoCattle-configurar-alertas-QA.png).
- [Vista del trabajador](evidencias/alertas-2026-10-24/GeoCattle-alertas-trabajador-QA.png).

### Activación local

El usuario reinició la API con Actualizar-Visualizacion.ps1. Se verificaron HTTP 200 en salud y GET /api/v1/settings, versión operativa 2 y capabilities.can_edit=true para el dueño. No se guardaron valores de prueba en el predio operativo.
