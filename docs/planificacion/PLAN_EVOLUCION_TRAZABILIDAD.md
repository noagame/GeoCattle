# Plan de evolución de la trazabilidad por predio

El objetivo es que cada alta de bovino, asociación de collar, registro sanitario, lectura y alerta pueda consultarse por predio, fecha y responsable. El primer incremento comprende saneamiento del flujo sanitario, exportaciones del predio y validación de las cuatro vistas en un entorno de pruebas accesible desde celular.

## Hallazgos de la revisión

| Área | Implementación actual | Trabajo propuesto |
| --- | --- | --- |
| Vacunación | El trabajador dispone de cuatro acciones, una de ellas **Registro sanitario**, cuyo formulario acepta vacuna o antibiótico. El producto se ingresa como texto libre. El veterinario registra directamente y el trabajador propone el registro o lo aplica si tiene confianza vigente para esa acción. | Agregar selección de productos aprobados dentro de **Vacuna**, manteniendo el flujo de cada perfil. Confirmar con el veterinario si la mención a «las cuatro» se refiere a las acciones visibles o a cuatro productos concretos. |
| Irregularidades sanitarias | El formulario exige un producto con una vía de su lista para vacuna y antibiótico. Permite productos opcionales en procedimientos y adapta los campos a los demás eventos. Completar una atención de vacunación o antibiótico exige un evento efectivo del mismo tipo. Una corrección conserva los datos históricos del producto cuando corresponde. | Confirmar el catálogo con el veterinario y validar los tres flujos desde el teléfono. |
| CSV | **Reportes del rebaño** incorpora vista previa y CSV para inventario, sanidad, agenda, mediciones, observaciones, asignaciones, alertas y actividad diaria. La ficha sanitaria abre los reportes con su bovino seleccionado. | Verificar las descargas desde Android e iOS durante la validación móvil. |
| Indicadores del dueño | **Reportes del rebaño** ofrece totales, alertas por período y rankings con evidencia de cobertura. El dueño y el administrador pueden consultar y exportar los cuatro reportes del predio activo. | Validar los umbrales de cobertura con varios collares en terreno. |
| Móvil y operación | React tiene menú móvil y estilos responsivos. El prototipo Windows ofrece un lanzador HTTPS para la red local y conserva el 8084 para operación en el servidor. | Validar desde un segundo equipo y ejecutar la matriz móvil con cuentas de prueba. La publicación remota y las pruebas de reconexión del puente pertenecen al despliegue piloto. |

Fuentes de los hallazgos. [Ficha sanitaria](../../frontend/src/V3Health.tsx) · [API de cambios e indicadores](../../backend/geocattle/v3_api.py) · [Registro diario](../../frontend/src/HardwarePage.tsx) · [CSV y resumen actuales](../../backend/geocattle/main.py) · [Captura](../../scripts/start_capture.py) · [Operación](../OPERACION.md)

## Secuencia de entregas

| Orden | Entrega | Dependencia | Criterio de aceptación |
| --- | --- | --- | --- |
| 0 | **Base de trabajo y recorrido de datos.** Levantar una base aislada y documentar, con IDs ficticios, el camino formulario → API → tablas → consulta. Registrar el estado del prototipo y de las migraciones antes de iniciar. | Ninguna. | Una persona del equipo puede seguir un bovino, su collar, una vacuna y una salida desde su origen hasta su consulta. Los cuatro perfiles se pueden probar en QA. |
| 1 | **Vacunas y agenda.** Revisar los casos señalados, corregir las validaciones y agregar el catálogo aprobado al formulario compartido. Guardar el nombre aplicado y los datos exigidos por la ficha para que el historial siga siendo legible si el catálogo cambia. | QA disponible. La reproducción puede comenzar mientras se confirma el catálogo. | El veterinario guarda una vacunación efectiva. El trabajador sin confianza genera una propuesta que el dueño puede decidir. Un evento incompatible no cierra la agenda y una corrección conserva la autoría y el historial. |
| 2 | **CSV de registros del rebaño.** Generar los ocho reportes por predio o bovino. Aplicar fechas locales al historial y presentar el inventario como consulta del estado actual. | Estabilizar la selección de registros sanitarios efectivos. | La vista previa utiliza los mismos filtros que el archivo. Un evento con varios productos exporta todos sus lotes con el mismo ID de evento. La API rechaza bovinos de otro predio. |
| 3 | **Reportes y KPI del dueño.** Añadir totales, series de alertas y rankings por bovino. Devolver los mismos resultados a pantalla y CSV. Medir consultas sobre volumen representativo antes de agregar índices o agregados persistentes. | QA y definiciones de métricas acordadas. Puede avanzar en paralelo con la corrección sanitaria. | Los totales coinciden con consultas verificadas. Los cortes por día, semana y mes usan la hora del predio. Las dos clasificaciones distinguen cobertura insuficiente y muestran la evidencia que sustenta el orden. |
| 4 | **Web móvil y tipografía.** Ajustar la interfaz responsiva existente y unificar tipografía, rótulos, acentos y unidades en pantallas clave. Probar primero acceso, selector de predio, mapa, formularios y CSV en dispositivos reales. | Entorno HTTPS de pruebas. La revisión del diseño puede iniciar junto con la entrega 0. | Las acciones de la matriz móvil funcionan en Android e iOS con cuentas ficticias. Se puede guardar y corregir un formulario sin desbordes y descargar el CSV de los perfiles autorizados. |
| 5 | **Preparación de despliegue remoto.** Preparar Compose, HTTPS y dominio. Validar restauración, migración, estado de servicios, capturas en cola y reversión de versión. | Entorno de pruebas desde el inicio. El paso a piloto requiere evidencia de QA, infraestructura elegida y destino de captura aprobado. | Se puede desplegar una versión identificada, restaurar en una instancia aislada y recuperar la entrega tras un corte. El acceso a PostgreSQL y los servicios internos queda restringido a la red prevista. |

## Definiciones para los reportes

- **Totales del predio.** Mostrar bovinos activos con permanencia vigente, collares inventariados y collares con asignación vigente como conteos distintos. Mostrar los módulos de software habilitados con su propio nombre. Indicar la fecha de corte de los totales.
- **Alertas.** Contar eventos únicos por su fecha de apertura y permitir agrupar por día, semana o mes, con filtro por tipo. El día sin eventos se presenta en relación con la cobertura disponible.
- **Movimiento.** Primera versión con `muestras moving / (muestras moving + muestras rest)` por bovino, vinculadas a la asignación vigente al capturar. Para obtener un puesto se requieren 10 muestras clasificadas y cobertura de al menos la mitad de los días transcurridos del período. La distancia recorrida requiere una métrica adicional con posiciones GNSS válidas, control de saltos y prueba en terreno.
- **Salidas.** Se cuentan aperturas de alertas `escape` por bovino y se muestran las geocercas asociadas. Para obtener un puesto se requieren al menos una alerta, 10 posiciones GNSS válidas durante una asignación de pastoreo y cobertura de al menos la mitad de los días transcurridos del período.

En PostgreSQL de QA se midió la ejecución SQL con 230.400 lecturas ficticias correspondientes a 32 collares y 30 días. Los tiempos fueron 0,7 ms para totales, 609 ms para la serie diaria, 2,61 s para movimiento y 1,35 s para salidas. La medición de salidas utilizó telemetría sin asignaciones de pastoreo. Los cálculos utilizan los índices existentes. Las pruebas de campo con varios collares quedan pendientes para validar los umbrales de cobertura.

## Tareas móviles por perfil

| Perfil | Tareas que debe completar desde el teléfono |
| --- | --- |
| Administrador | Iniciar sesión con MFA, entrar al panel global y atender una solicitud de soporte. |
| Dueño | Seleccionar predio, revisar mapa y alertas, decidir una propuesta y descargar el reporte. |
| Veterinario | Buscar por DIIO, registrar o corregir una vacuna, revisar la agenda y descargar la ficha diaria. |
| Trabajador | Buscar un bovino, reportar una vacuna administrada y consultar la decisión. |

La primera entrega móvil se plantea sobre la web responsiva. Un entorno de pruebas con certificado confiable permite validar la descarga, las sesiones y funciones dependientes de contexto seguro como `crypto.randomUUID()`.

## Recorrido técnico para el informe

| Dato | Origen y trazabilidad |
| --- | --- |
| Bovino | Formulario → `POST /api/v1/animals` → `animals` y `animal_holdings` en la misma transacción. |
| Collar | Inventario → `devices`. Asignación → `assignments` con vigencia. La captura identifica el collar y vincula la lectura de `telemetry` al bovino que correspondía al momento de observación. |
| Usuario | Invitación → `invitations`. Aceptación → `users` si corresponde, `farm_memberships` y consumo de la invitación en la misma transacción. |
| Vacuna | Formulario → `POST /api/v1/v3/changes` → `change_requests` y, al aplicar, `change_decisions`, `health_events`, `health_treatments` y `change_applications`. |
| Alerta de salida | Lectura válida → regla de geocerca → `events`. Las acciones humanas se conservan en `event_actions`. |

[Esquema y documentación de base de datos](../MODELO_BASE_DATOS.md) · [Contratos de API](../CONTRATO_API.md)

## Inicio del despliegue

Para las pruebas de la parte 4 en el mismo lugar, conecta los dispositivos a un Wi-Fi compartido y usa el [acceso HTTPS local de Windows](../DESARROLLO_LOCAL.md#acceso-https-desde-otro-dispositivo). Las pruebas con un segundo dispositivo y los recorridos por perfil de la matriz móvil se verifican por separado.

1. Levantar **staging** en Docker Compose con PostgreSQL/PostGIS, API, worker, web y TLS. Usar una base ficticia o una copia autorizada y depurada. Configurar un dominio o nombre de pruebas alcanzable desde los celulares.
2. Verificar las cuatro sesiones y el acceso por predio. Registrar versión, migraciones, estado de servicios y resultado de las pruebas. En la revisión del 19 de noviembre se confirmó la migración `007` en la instancia nativa. La `008` de Gmail se encuentra preparada en la copia de trabajo y la activación del envío requiere un remitente y la configuración de entrega.
3. Probar el flujo **estación T3 → USB en Windows → cola SQLite → API HTTPS → PostgreSQL** con un destino explícito. Revisar el lanzador que hoy limita el destino a desarrollo. Probar recuperación tras corte y conservar las asociaciones de captura. Verificar compatibilidad de restauración con la versión de PostgreSQL/PostGIS del destino.
4. Preparar para piloto `COOKIE_SECURE`, orígenes autorizados, MFA de administración, secretos por entorno, respaldo diario y restauración ensayada. Verificar los objetivos K03, K05, K06 y K11 con las pruebas y ventanas del informe. Publicar cuando el host, el dominio y la ventana de migración estén definidos.

[Operación de piloto](../OPERACION.md) · [Verificación del informe](../REQUISITOS_INFORME_2.md)

## Primer bloque de trabajo

- **Datos y API.** Preparar el caso reproducible de vacuna sin producto, cierre con evidencia de tipo distinto y corrección de tratamiento con lote. Revisar el uso de claves foráneas, autoría, vigencias y transacciones con datos ficticios.
- **Interfaz e integración.** Revisar el formulario compartido, recoger los nombres y campos del catálogo con el veterinario, y verificar el flujo en un ancho de teléfono. Preparar staging HTTPS en paralelo.
- **Revisión cruzada.** Usar la distribución propuesta en la planificación existente. Fabián coordina datos, API y seguridad. Boris coordina interfaz, integración IoT y validación. El primer incremento termina con evidencia por rol y un recorrido de datos reproducible.

[Distribución propuesta del equipo](CARTA_GANTT_V3.md)
