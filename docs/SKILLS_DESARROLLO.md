# Skills para desarrollar GeoCattle

Consulta del catálogo oficial `openai/skills/skills/.curated` realizada el 7 de octubre de 2026 antes de comenzar la implementación. Se utilizó la skill del sistema `skill-installer` para consultar el catálogo. El usuario pidió buscar skills, no instalarlas globalmente; no se modificó la configuración personal de Codex.

| Skill | Uso pertinente | Momento recomendado |
|---|---|---|
| [playwright](https://github.com/openai/skills/tree/main/skills/.curated/playwright) | Probar login, formularios, mapa, geocercas, alertas y vista móvil en navegador | Cada incremento funcional |
| [playwright-interactive](https://github.com/openai/skills/tree/main/skills/.curated/playwright-interactive) | Inspeccionar visualmente flujos y depurar problemas de interfaz | Durante integración frontend/backend |
| [security-best-practices](https://github.com/openai/skills/tree/main/skills/.curated/security-best-practices) | Revisar explícitamente seguridad de Python/FastAPI y TypeScript/React | Revisión de seguridad antes del piloto |
| [security-threat-model](https://github.com/openai/skills/tree/main/skills/.curated/security-threat-model) | Modelar amenazas en sesión, separación de predios, MQTT, ingestión y notificaciones | Antes de exposición remota |
| [gh-fix-ci](https://github.com/openai/skills/tree/main/skills/.curated/gh-fix-ci) | Diagnosticar pruebas fallidas en GitHub Actions | Al conectar el repositorio a GitHub |
| [sentry](https://github.com/openai/skills/tree/main/skills/.curated/sentry) | Consultar incidentes de una instancia Sentry ya configurada | Operación posterior; no sustituye monitoreo local |

Las skills `aspnet-core`, `winui-app` y las de despliegue exclusivo de frontend no corresponden al stack definido en el informe. Figma puede ser útil si se proporciona un diseño en ese servicio; no es necesario para esta implementación. Sites no se utiliza porque se desarrolla el proyecto local especificado por el informe, con FastAPI y PostgreSQL/PostGIS.

Las skills orientan al agente y no son dependencias ejecutables del SaaS. La aplicación se implementa con las tecnologías del informe, pruebas automatizadas y verificación de navegador, sin exigir instalar skills para arrancar el sistema.

Fuentes: [catálogo oficial](https://github.com/openai/skills/tree/main/skills/.curated), [instrucciones de security-best-practices](https://github.com/openai/skills/blob/main/skills/.curated/security-best-practices/SKILL.md), [instrucciones de Playwright](https://github.com/openai/skills/blob/main/skills/.curated/playwright/SKILL.md).
