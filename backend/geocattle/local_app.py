"""Aplicacion y frontend compilado en un mismo origen, solo para inicio local."""
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .main import app

frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
