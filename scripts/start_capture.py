"""Portable one-step host USB capture for a native Windows or Docker backend."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def capture_context(args):
    backend = args.backend
    if backend == 'auto':
        backend = 'native' if platform.system() == 'Windows' and (ROOT / '.env.academic').exists() and args.env_file is None else 'docker'
    if backend == 'native' and platform.system() != 'Windows':
        raise SystemExit('El arranque nativo preparado usa PostgreSQL Windows. En Linux utiliza --backend docker.')
    env_file = args.env_file or ROOT / ('.env.academic' if backend == 'native' else '.env.docker')
    env_file = Path(env_file)
    if not env_file.is_absolute():
        env_file = ROOT / env_file
    if not env_file.exists():
        raise SystemExit('Prepara primero el backend y su archivo privado: python scripts/docker_project.py prepare --environment development')
    from adapters.lora_usb import load_env
    values = load_env(env_file)
    if values.get('APP_ENV') != 'development' or values.get('SIMULATION_ENABLED', '').lower() != 'false':
        raise SystemExit('La captura fisica requiere development y SIMULATION_ENABLED=false; no se enviaran datos reales a simulacion.')
    default_directory = '.runtime/capture' if backend == 'native' else values.get('USB_CAPTURE_DIR', '.runtime/docker-capture')
    directory = args.directory or Path(default_directory)
    directory = Path(directory)
    if not directory.is_absolute():
        directory = ROOT / directory
    base = (args.api_url or f"http://127.0.0.1:{values.get('WEB_PORT', '8084' if backend == 'native' else '8086')}").rstrip('/')
    return {'backend': backend, 'env_file': env_file, 'directory': directory, 'base_url': base, 'environment': 'development'}


def recent_status(directory=None):
    directory = directory or ROOT / '.runtime/capture'
    try:
        data = json.loads((directory / 'status.json').read_text(encoding='utf-8-sig'))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['updated_at'])).total_seconds()
        return data if 0 <= age < 15 else None
    except (OSError, ValueError, KeyError):
        return None


def api_ready(base='http://127.0.0.1:8084', expected='development'):
    try:
        with urllib.request.urlopen(base + '/api/v1/health', timeout=3) as response:
            data = json.load(response)
            if data.get('status') == 'ok' and data.get('environment') != expected:
                raise SystemExit('La API pertenece a otro entorno; se conserva la captura y no se abre el USB.')
            return data.get('status') == 'ok'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='auto')
    parser.add_argument('--backend', choices=('auto', 'native', 'docker'), default='auto')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--api-url', help='Base URL, without /api/v1')
    args = parser.parse_args()
    os.chdir(ROOT)
    context = capture_context(args)
    print('GEOCATTLE - CAPTURA POR IDENTIDAD USB', flush=True)
    current = recent_status(context['directory'])
    paused = current and str(current.get('error') or '').startswith(('Captura pausada', 'Captura detenida'))
    if current and current.get('capture_version') != 2 and not paused:
        raise SystemExit('El lector anterior sigue activo con COM fijo. Pausalo antes de abrir el nuevo iniciador.')
    if not api_ready(context['base_url'], context['environment']):
        print('Iniciando servicios locales; datos conservados...', flush=True)
        if context['backend'] == 'native':
            command = [sys.executable, '-u', 'scripts/prototype_windows.py', 'start', '--no-usb']
        else:
            command = [sys.executable, '-u', 'scripts/docker_project.py', 'start', '--environment', 'development', '--env-file', str(context['env_file'])]
        subprocess.run(command, cwd=ROOT, check=True)
        for _ in range(30):
            if api_ready(context['base_url'], context['environment']):
                break
            time.sleep(.5)
        else:
            raise SystemExit('La API no responde; las capturas existentes se conservan.')
    if current and current.get('capture_version') == 2 and current.get('state') != 'stopped' and not paused and args.port.lower() == 'auto':
        print('La captura ya esta iniciada. Esperara la misma receptora si se desconecta.', flush=True)
        return 0
    print('Cierra Monitor Serie y Plotter. Deja abierta esta ventana.', flush=True)
    print('Primer inicio: conecta solo la receptora por USB de datos y enciende el emisor.', flush=True)
    print('Se recordara al recibir LoRa con RSSI/SNR, aunque despues cambie su puerto.', flush=True)
    print('Ctrl+C detiene la captura sin borrar datos. GeoCattle: ' + context['base_url'], flush=True)
    return subprocess.call([sys.executable, '-u', '-m', 'adapters.lora_usb', '--port', args.port,
                            '--env-file', str(context['env_file']), '--directory', str(context['directory']),
                            '--url', context['base_url'] + '/api/v1/ingest/telemetry'], cwd=ROOT)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Captura detenida; datos conservados.')
