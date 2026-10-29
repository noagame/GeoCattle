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


def ask_receiver_mode():
    print('Selecciona el metodo ANTES de buscar el puerto USB:', flush=True)
    print('  1. Directo: T3 original / collar -> T3', flush=True)
    print('  2. Gateways: T3 base / collar -> XIAO -> T3', flush=True)
    while True:
        try:
            option = input('Opcion [1 o 2]: ').strip()
        except EOFError:
            raise SystemExit('No se eligio metodo. Usa --receiver-mode direct o --receiver-mode gateways.')
        if option in ('1', '2'):
            return 'direct' if option == '1' else 'gateways'
        print('Escribe 1 o 2.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='auto')
    parser.add_argument('--receiver-mode', choices=('direct', 'gateways'))
    parser.add_argument('--select-mode', action='store_true', help='Elegir el metodo antes de enumerar o abrir USB')
    parser.add_argument('--backend', choices=('auto', 'native', 'docker'), default='auto')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--api-url', help='Base URL, without /api/v1')
    args = parser.parse_args()
    os.chdir(ROOT)
    context = capture_context(args)
    print('GEOCATTLE - CAPTURA POR METODO E IDENTIDAD USB', flush=True)
    if args.select_mode and args.receiver_mode:
        parser.error('Utiliza --select-mode o --receiver-mode, no ambos.')
    selected_mode = ask_receiver_mode() if args.select_mode else args.receiver_mode
    current = recent_status(context['directory'])
    paused = current and str(current.get('error') or '').startswith(('Captura pausada', 'Captura detenida'))
    if current and current.get('capture_version') != 2 and not paused:
        raise SystemExit('El lector anterior sigue activo con COM fijo. Pausalo antes de abrir el nuevo iniciador.')
    active = current and current.get('state') != 'stopped' and not paused
    if selected_mode and active and current.get('receiver_profiles_version') != 1:
        raise SystemExit('El capturador anterior no admite cambiar de metodo. Pausa solo la captura y abre de nuevo este iniciador; los datos se conservan.')
    from adapters.receiver_profiles import preferred_mode, select_mode
    mode = select_mode(context['directory'], selected_mode) if selected_mode else preferred_mode(context['directory'])
    print('Metodo elegido: ' + ('Directo' if mode == 'direct' else 'Gateways') + '. El puerto se buscara por identidad USB.', flush=True)
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
        if selected_mode:
            print('Cambio solicitado al unico capturador activo: cerrara el receptor anterior y buscara la placa del metodo elegido.', flush=True)
        else:
            print('La captura ya esta iniciada. Esperara la misma receptora si se desconecta.', flush=True)
        return 0
    print('Cierra Monitor Serie y Plotter. Deja abierta esta ventana.', flush=True)
    print('Conecta la T3 del metodo elegido por USB de datos y enciende el collar.', flush=True)
    print('Si falta esa T3 se esperara su identidad, sin usar la otra ni los XIAO.', flush=True)
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
