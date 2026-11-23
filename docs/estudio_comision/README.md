# Guía de estudio y defensa · GeoCattle

**Versión estudiada:** `main` · `8d15510e83e155b3632b6fb9e50f121f9335e48e` · revisión documental del 29 de octubre de 2026, America/Santiago.

## Qué contiene y cómo usarlo

Esta colección enseña a seguir una lectura desde el collar hasta el navegador, explicar una decisión autorizada y defender los límites del prototipo. Son **21 archivos completos**, incluido este índice, con 60 preguntas respondidas, ejercicios, diagramas y referencias a una versión fija del repositorio.

La revisión es documental. No se cambiaron código, configuraciones, bases, servicios ni placas; no se publicaron commits. Se consultaron referencias remotas y CI pública; se validó solo el ejemplo sintético mediante funciones puras, sin publicarlo. Las eliminaciones locales de documentación se conservaron y sus contenidos necesarios se consultaron en Git.

## Versión y etiquetas

- Principal: `main` y `origin/main`, `8d15510e83e155b3632b6fb9e50f121f9335e48e`.
- Checkout conservado: `dev/software`, `d7f29b7e9cd9199cc11d75615a6cf62533582143`; mismo contenido al corte, distinta historia de merge.
- Integración: `develop`, `dda2ba74506bec8f76fff1fe41a0c85e40362621`.
- Hardware WIP: `35747545a6560222b0b4306c570b9b5e6e554f67`; alcance y fallos en [pendientes](19_DISCREPANCIAS_Y_PENDIENTES.md).
- Fecha: 29 de octubre de 2026, America/Santiago. Los enlaces de código están fijados al SHA, no a una rama móvil.

**Implementado:** encontrado en el código. **Verificado en software:** prueba/evidencia identificada con entorno. **Verificado con hardware:** evidencia física histórica identificada; no repetida ahora. **Propuesto:** evolución que no debe presentarse como hecha. **Pendiente/no documentado:** falta una fuente o validación específica. «Interpretación técnica» distingue razonamiento del revisor de la motivación documentada del autor.

## Índice y avance

- [x] [00 · Problema, alcance y discurso de dos minutos](00_PROYECTO_Y_ALCANCE.md)
- [x] [01 · Componentes, despliegue y secuencias](01_ARQUITECTURA_GENERAL.md)
- [x] [02 · Orden de lectura y símbolos clave](02_MAPA_Y_LECTURA_DEL_CODIGO.md)
- [x] [03 · Contratos, errores, identidad y transacciones](03_BACKEND_Y_API.md)
- [x] [04 · Modelo, tiempo, PostGIS e historia](04_BASE_DE_DATOS_Y_TRAZABILIDAD.md)
- [x] [05 · Interfaz, borradores, mapas y versiones](05_FRONTEND_MAPAS_Y_FLUJOS.md)
- [x] [06 · Sesiones, permisos, contexto y MFA](06_SEGURIDAD_ROLES_Y_MULTIPREDIO.md)
- [x] [07 · Qué sabemos de placas, sensores y energía](07_IOT_COMPONENTES_Y_FIRMWARE.md)
- [x] [08 · LoRa/LoRaWAN, USB, HTTP y MQTT](08_COMUNICACION_Y_PROTOCOLOS.md)
- [x] [09 · Paquete sintético validado, de radio a pantalla](09_RECORRIDO_DE_UN_DATO.md)
- [x] [10 · Ventanas, condiciones, atención y ubicación histórica](10_REGLAS_GEOCERCAS_Y_ALERTAS.md)
- [x] [11 · Pérdidas, colas, ACK y recuperación](11_FALLOS_RECUPERACION_Y_CONSISTENCIA.md)
- [x] [12 · Entornos, procesos, respaldos y recuperación](12_DESPLIEGUE_Y_OPERACION.md)
- [x] [13 · Matriz de evidencia y cobertura](13_PRUEBAS_Y_EVIDENCIAS.md)
- [x] [14 · Qué no podemos garantizar y cómo medirlo](14_LIMITES_RESTRICCIONES_Y_RIESGOS.md)
- [x] [15 · Justificaciones y propuestas de evolución](15_DECISIONES_Y_ALTERNATIVAS.md)
- [x] [16 · Demo de 12 minutos y planes ante fallos](16_DEMOSTRACION_Y_CONTINGENCIAS.md)
- [x] [17 · 60 preguntas con respuesta y repregunta](17_PREGUNTAS_DE_LA_COMISION.md)
- [x] [18 · Rutas 1/7/14 días, glosario y repaso](18_PLAN_DE_ESTUDIO_Y_GLOSARIO.md)
- [x] [19 · Diferencias entre fuentes y preguntas al equipo](19_DISCREPANCIAS_Y_PENDIENTES.md)

## Orden recomendado y conocimientos previos

Primero 00 → 01 → 09 para tener el relato completo. Después 02 → 03 → 04 para código y persistencia; 07 → 08 → 11 para IoT y comunicación; 05 → 06 → 10 para interfaz, permisos y reglas. Continúa 12 → 13 → 14 → 15 → 19 para operación, evidencia y límites. Termina ensayando 16–18.

No necesitas dominar previamente todos los frameworks. Antes de profundizar asegúrate de distinguir cliente/servidor, variable/función, tabla/fila, identificación/autorización y señal/dato. El [glosario](18_PLAN_DE_ESTUDIO_Y_GLOSARIO.md) los conecta con los archivos reales.

## Lista de preparación personal

- [ ] Puedo explicar el problema y sus objetivos formales sin confundirlos con funciones observadas.
- [ ] Dibujo los procesos y señalo dónde puede perderse un paquete.
- [ ] Ubico decoder, archivo, endpoint, ingestión, consulta y componente de interfaz.
- [ ] Distingo DIIO, UUID, hardware_id, EUI y sesión/secuencia.
- [ ] Resuelvo una lectura tardía y una reasignación sin reescribir la historia.
- [ ] Explico LoRa P2P frente a LoRaWAN y cada ACK por separado.
- [ ] Puedo demostrar un rechazo de permisos conceptualmente desde la ruta del servidor.
- [ ] Calculo las ventanas con T y sé por qué el worker agrega demora.
- [ ] Relaciono pruebas con SHA/entorno y no las uso como capacidad física medida.
- [ ] Reconozco cinco pendientes de terreno y propongo cómo validarlos.
- [ ] Practiqué la demo y un fallo sin alterar evidencia o desactivar seguridad.
- [ ] Respondí preguntas de las seis secciones del banco y revisé mis fuentes.

## Evidencia de partida y dudas críticas

Los cuatro checks de [main](https://github.com/noagame/GeoCattle/actions/runs/40957908450) constan aprobados para el SHA citado. Eso respalda regresión de software, no autonomía, alcance, diagnóstico o capacidad de muchos emisores. Los relatos físicos de 22–23/10 son evidencia histórica con condiciones; sus datos crudos privados y firmware no se inspeccionaron aquí.

Antes de la comisión, prioriza conseguir objetivos/criterios aprobados, firmware y BOM de las placas que se mostrarán, modo exacto de captura, T administrativo, evidencia física autorizada y plan de contingencia. Si falta una respuesta, usa la matriz de pendientes; no llenes el vacío con una especificación «típica».

## Lectura del código y evidencia

- [README.md](https://github.com/noagame/GeoCattle/blob/8d15510e83e155b3632b6fb9e50f121f9335e48e/README.md)
- [docs/DESARROLLO_COLABORATIVO.md](https://github.com/noagame/GeoCattle/blob/8d15510e83e155b3632b6fb9e50f121f9335e48e/docs/DESARROLLO_COLABORATIVO.md)
- [.github/workflows/validacion.yml](https://github.com/noagame/GeoCattle/blob/8d15510e83e155b3632b6fb9e50f121f9335e48e/.github/workflows/validacion.yml)

[Volver al índice](README.md)
