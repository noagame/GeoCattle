# Aplicación web

## Propósito y alcance

Vite sirve la interfaz React y los recursos en `public/`. `vite.config.ts` dirige `/api` al backend local en el puerto 8000. `tests/geofenceDraft.test.mjs` cubre el borrador de geocercas.

## Guía de trabajo

- Si cambian las dependencias, conserva sincronizados `package.json` y `package-lock.json`. `npm ci` es el flujo reproducible de CI.
- Vite sirve la carpeta `.runtime/mapa-satelital/` de la raíz del repositorio en `/mapa-local/satelite/` en desarrollo y previsualización. El build excluye esta carpeta. Conserva el manifiesto, la atribución y la cuadrícula de respaldo. [Mapa satelital](../docs/MAPA_SATELITAL.md)
- Vite sirve igualmente `.runtime/mapa-osm/` en `/mapa-local/osm/`. El build excluye esta carpeta.

## Verificación

Desde `frontend/`, ejecuta `npm ci`, `npm test` y `npm run build`.

`tests/deviceCandidates.test.mjs` comprueba que el inventario de collares y el selector de predio escapan sus nombres al renderizar.

## Child DOX Index

- [src/AGENTS.md](src/AGENTS.md) — interfaz, API web, mapas, geocercas y telemetría.
