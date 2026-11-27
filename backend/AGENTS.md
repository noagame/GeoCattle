# Backend Python

## Propósito y alcance

Este directorio contiene el paquete FastAPI, el contenedor, las dependencias y pytest. `pyproject.toml` declara requerimientos y `uv.lock` y `requirements.lock` alimentan los flujos de instalación.

## Guía de trabajo

- Revisa qué flujos consumen cada archivo de dependencias al cambiar una versión. CI instala `requirements.lock` y el desarrollo con uv usa `uv.lock`.
- XlsxWriter genera las exportaciones en ejecución. openpyxl pertenece al extra `test` y al target Docker `test`, donde comprueba los archivos en las pruebas de integración.
- Los cambios en esquema se coordinan con [database](../database/AGENTS.md) y los cambios de arranque con [scripts](../scripts/AGENTS.md).
- La imagen incluye los adaptadores para compartir el parser bus_v1 con el endpoint de lotes HTTPS de la T3.

## Verificación

Desde `backend/`, prepara dependencias con `uv sync --extra test`. Para la integración sigue los requisitos de [tests](tests/AGENTS.md).

## Child DOX Index

- [geocattle/AGENTS.md](geocattle/AGENTS.md) — API, reglas, seguridad, ingesta y procesos.
- [tests/AGENTS.md](tests/AGENTS.md) — pruebas de reglas, configuración e integración.
