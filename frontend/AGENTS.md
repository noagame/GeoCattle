# Aplicación web

## Propósito y alcance

Vite sirve la interfaz React y los recursos en `public/`. `vite.config.ts` dirige `/api` al backend local en el puerto 8000. `tests/geofenceDraft.test.mjs` cubre el borrador de geocercas.

## Guía de trabajo

- Si cambian las dependencias, conserva sincronizados `package.json` y `package-lock.json`. `npm ci` es el flujo reproducible de CI.
- Las capas cartográficas locales en `public/mapa-local/` se consumen por URL desde `Map.tsx`. Conserva el manifiesto, la atribución y el respaldo cartográfico al actualizar teselas. El generador actual está en [scripts](../scripts/AGENTS.md).

## Verificación

Desde `frontend/`, ejecuta `npm ci`, `npm test` y `npm run build`.

`tests/deviceCandidates.test.mjs` comprueba que el inventario de collares y el selector de predio escapan sus nombres al renderizar.

## Child DOX Index

- [src/AGENTS.md](src/AGENTS.md) — interfaz, API web, mapas, geocercas y telemetría.
