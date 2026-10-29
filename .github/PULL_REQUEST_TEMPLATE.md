## Problema y resultado

Describe el problema concreto y el comportamiento que queda al aplicar este cambio.

## Area y destino

- Area: software / captura de hardware / contrato compartido / infraestructura / documentacion.
- Rama de destino: normalmente `develop`; `main` se actualiza desde una integracion revisada.
- Archivos compartidos o dependencias de otro PR:

## Compatibilidad

- Formatos o endpoints afectados y compatibilidad conservada:
- Migraciones nuevas, si existen; indicar si requieren una base de prueba aislada:
- Riesgo de regresion o rendimiento y evidencia pertinente:

## Validacion

Indica los comandos ejecutados y sus resultados. Diferencia compilacion, pruebas automaticas y pruebas con placas reales; no marques como probado lo que sigue pendiente.

## Revision

- [ ] Revise el diff completo y conserve los cambios ajenos relevantes.
- [ ] Los commits no incluyen credenciales, `.env`, capturas privadas ni bases locales.
- [ ] Los cambios de contrato incluyen pruebas de compatibilidad de software y captura.
- [ ] El PR esta en borrador si su integracion o validacion esta incompleta.

Antes de integrar, el otro colaborador debe revisar el PR y las comprobaciones de CI deben finalizar correctamente.
