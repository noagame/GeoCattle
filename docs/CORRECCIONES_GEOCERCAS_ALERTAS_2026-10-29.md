# Correcciones de geocercas, alertas y revisión térmica

## Hallazgos y cambios

El formulario anterior ya compartía los puntos del mapa y de las coordenadas, pero la edición individual estaba oculta en un desplegable y los puntos carecían de identidad estable. El nuevo editor ofrece marcadores numerados y arrastrables, selección sincronizada, coordenadas editables y una secuencia común. Conserva los valores vacíos como inválidos, sin convertirlos a cero. El borrador permite deshacer adiciones, ediciones, arrastres y eliminaciones. Cancelar una confirmación no modifica la geometría. Esc, cerrar y Cancelar solicitan confirmación si hay cambios; recargar o salir de la página activa el aviso del navegador.

Eliminar un punto y limpiar todos los puntos son acciones diferentes y requieren confirmaciones con su alcance. Importar sobre un borrador también requiere confirmación. Se rechazan duplicados, coordenadas fuera de WGS84, menos de cuatro vértices y polígonos cruzados o sin área; PostGIS conserva la validación final. La numeración visible depende del orden y el identificador del punto permanece estable durante su edición.

## Modelo y compatibilidad

`004_geofence_identity_event_position.sql` agrega `geofence_key` como identidad estable. Los UUID de cada versión se conservan: las asignaciones y eventos anteriores mantienen sus referencias exactas. Las versiones antiguas de un mismo sector se agrupan bajo la identidad de su primera versión. La unicidad pasa de sector a identidad y versión; hay una sola versión activa por identidad, pero varias geocercas activas por sector.

`geofence_sectors` guarda los sectores asociados a cada versión con claves compuestas que impiden cruces entre predios. `sector_id` conserva el sector principal por compatibilidad y como sector utilizado por la asignación de pastoreo. Asociar sectores secundarios permite organizar y filtrar la misma geometría, sin duplicarla ni otorgar un permiso espacial adicional. Cambiar el sector principal exige transferir primero las asignaciones de pastoreo vigentes. Las asociaciones con sectores secundarios también se conservan en el historial de versiones.

La creación con `expected_version=0` crea una geocerca independiente. Para editar se envían `geofence_key` y la versión esperada. Se acepta temporalmente la escritura legada sin identidad solo cuando hay exactamente una geocerca activa con ese sector principal; si hay varias, la API devuelve 409 y exige seleccionar la identidad. Los clientes no deben deducir la identidad a partir del sector.

Un animal continúa teniendo una asignación explícita a una versión de geocerca. Crear zonas vecinas o superpuestas no modifica su zona permitida ni une polígonos. Editar una geocerca transfiere únicamente las asignaciones de esa identidad a su nueva versión, cierra sus intervalos previos y reinicia su evaluación consecutiva. Las otras geocercas no cambian.

## Posición histórica de pérdida de comunicación

Al abrir `communication_timeout`, se conserva `events.last_position_id`, separado de la lectura que origina otros tipos de eventos. La búsqueda usa únicamente GPS válido del mismo predio, collar, animal y asociación vigente al detectar el evento, capturado y recibido antes o en esa detección. Paquetes sin fix, futuras capturas, reentregas y llegadas posteriores no sustituyen esa evidencia. Un trigger impide cambiar la referencia después de crear el evento.

La migración completa posiciones de eventos anteriores solo cuando puede reconstruir ese contexto con lecturas recibidas a tiempo. Si no existe evidencia compatible se muestra un estado sin ubicación. La API entrega la lectura, el hardware y la antigüedad al detectar el evento. El mapa avisa que es una ubicación histórica y no la ubicación actual. Reconocer o concluir la atención no modifica la condición técnica; la reconexión puede resolverla conservando la posición histórica.

## Temperatura reportada por el collar

Los adaptadores CSV V4 usan `temp_c`; JSON V5 recibe `t` y lo convierte al contrato CSV. Ambos terminan en `surface_temperature_c`. Los archivos de integración disponibles no demuestran el modelo de sensor, contacto con el animal, montaje, calibración ni compensación ambiental. El nombre del campo es un contrato de software, no prueba de qué magnitud mide físicamente el montaje. Esa identificación y la validación en terreno quedan pendientes del responsable de hardware.

Se conserva el valor legado de 39,5 °C; no se declara validado. La regla es preventiva: una lectura nueva y reciente mayor o igual al umbral abre el evento; una inferior lo resuelve. No es temperatura corporal interna ni diagnóstico. Las lecturas ausentes no abren ni resuelven eventos térmicos. La API rechaza valores fuera de -60 a 100 °C; los adaptadores convierten mediciones no utilizables a ausencia según su contrato. Duplicados y paquetes atrasados se almacenan/deduplican sin reevaluar el estado vigente.

Guardar un umbral no habilita la regla. `PREVENTIVE_RULES_VALIDATED` sigue siendo requisito para activarla fuera de simulación, y el servidor conserva la autorización por predio. Reglas del predio y Configurar alertas usan el mismo componente y la misma API.

La evaluación actual de una sola lectura puede oscilar alrededor del umbral. Una ventana de persistencia e histéresis pueden ser útiles, pero no se introduce un número arbitrario de muestras, minutos o grados sin conocer frecuencia, precisión y montaje. La elección de esos parámetros y el umbral debe basarse en la validación física. El texto de interfaz explicita el funcionamiento actual y sus límites.

## Verificación

La migración se prueba en una base QA independiente restaurada desde el respaldo previo. Se comparan los registros existentes antes y después, y se repite el migrador para comprobar idempotencia. Las pruebas del backend usan transacciones reversibles en esa base, no la aplicación en ejecución. Las pruebas del editor cubren identidad, edición, eliminación, arrastre, deshacer, importación y geometrías inválidas.

Comandos: `npm test --prefix frontend`, `npm run build --prefix frontend`, y pytest con `TEST_DATABASE_URL` de una base PostgreSQL/PostGIS de QA migrada. Los resultados de esta sesión están en `.runtime/revision-20261029/` y no contienen credenciales.

## Resultado de esta entrega

- Migración verificada desde el respaldo en una base QA: 3 versiones de geocerca, 70 asignaciones de pastoreo, 569 lecturas y 75 eventos conservaron sus registros originales. Se reconstruyeron 70 posiciones históricas compatibles. La repetición del migrador no produjo cambios adicionales.
- Backend: 123 pruebas aprobadas. Frontend: 4 pruebas del editor aprobadas y compilación de producción correcta. Advertencias no bloqueantes: deprecación del adaptador httpx de Starlette y tamaño del bundle principal de Vite.
- Navegador QA: dueño y administrador con MFA/contexto de predio; creación de geocerca adicional sin sustituir la original; asociaciones a dos sectores; selección, edición y arrastre individual; eliminación confirmada/cancelada y deshacer; confirmaciones de limpieza y cierre; adición combinada desde mapa y coordenadas; versión nueva conservando la otra geocerca; visualización de ubicación histórica y bloqueo térmico sin validación.
- Despliegue local: API y PostgreSQL saludables; web, worker y broker en ejecución. Verificación HTTP de acceso, geocercas, alertas y reglas; 70 animales y 70 collares conservados. Los hashes de los 24 módulos de backend y de los 6 archivos del frontend desplegado coinciden con la versión verificada.
- Evidencia local: `.runtime/revision-20261029/migration.json`, `backend-tests.log`, `frontend-tests.log`, `frontend-build.log`, `live-checks.json`, `editor-geocercas.jpg` y `alerta-ubicacion.jpg`. Las capturas utilizan exclusivamente datos ficticios de QA.
