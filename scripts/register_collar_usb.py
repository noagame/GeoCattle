"""Identify a newly connected GeoCattle collar and submit it for review."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.lora_json import decode_json
from adapters.lora_usb import load_env
from adapters.receiver_profiles import MODES, load_profile
from adapters.serial_receiver import ReceiverSelectionError, choose_receiver, enumerate_ports


def connected_usb():
    return {port.device: port for port in enumerate_ports() if port.vid is not None and port.pid is not None}


def collar_descriptor(line):
    try:
        item = json.loads(line)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(item, dict) or item.get('type') != 'geocattle_collar' or type(item.get('version')) is not int or item['version'] != 1:
        return None
    hardware_id = item.get('hardware_id')
    interval = item.get('interval_seconds')
    if (not isinstance(hardware_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}', hardware_id)
            or item.get('transport') != 'academic' or type(interval) is not int or not 30 <= interval <= 86400):
        return None
    descriptor = {'hardware_id': hardware_id, 'interval_seconds': interval, 'transport': 'academic'}
    firmware_version = item.get('firmware_version')
    if isinstance(firmware_version, str) and 1 <= len(firmware_version) <= 100:
        descriptor['firmware_version'] = firmware_version
    return descriptor


def legacy_collar_descriptor(line):
    if not line.lstrip().startswith(b'{'):
        return None
    try:
        payload, _ = decode_json(line.decode('utf-8').strip(), datetime.now(timezone.utc))
    except (ValueError, OverflowError):
        return None
    quality = payload['quality']
    if 'radio' in quality:
        # A receiver envelope identifies a collar heard over the air.
        return None
    return {
        'hardware_id': payload['hardware_id'],
        'interval_seconds': max(30, (quality['period_ms'] + 999) // 1000),
        'transport': 'academic',
    }


def read_collar(port):
    import serial

    with serial.Serial(port, baudrate=115200, timeout=.25, write_timeout=1) as link:
        started = time.monotonic()
        # The legacy sketch prints every 45 s and does not answer queries.
        deadline = started + 55
        next_query = started
        pending = bytearray()
        discard_line = False
        while (now := time.monotonic()) < deadline:
            if next_query <= now < started + 12:
                link.write(b'\nGEOCATTLE_IDENTIFY_V1\n')
                next_query = now + 1
            chunk = link.read_until(size=1024)
            if not discard_line:
                pending.extend(chunk)
                discard_line = len(pending) > 1024
                if discard_line:
                    pending.clear()
            if chunk.endswith(b'\n'):
                if not discard_line:
                    descriptor = collar_descriptor(pending) or legacy_collar_descriptor(pending)
                    if descriptor:
                        return descriptor
                pending.clear()
                discard_line = False
    raise ValueError('No se recibió la identificación USB ni un paquete JSON V5 del collar. '
                     'Revisa que esté encendido y pueda completar un envío LoRa.')


def post_candidate(opener, base, descriptor, key, farm_id=None):
    headers = {'Content-Type': 'application/json', 'X-Ingest-Key': key}
    if farm_id:
        headers['X-Farm-ID'] = str(farm_id)
    request = Request(base + '/api/v1/v3/device-candidates',
                      json.dumps({**descriptor, 'source': 'usb'}).encode(), headers, method='POST')
    try:
        with opener.open(request, timeout=5) as response:
            result = json.load(response)
    except HTTPError as error:
        raise api_error(error) from error
    if not isinstance(result, dict) or not result.get('id') or result.get('status') != 'pending':
        raise ValueError('La API no confirmó la detección USB.')
    return result


def api_error(error):
    with error:
        try:
            detail = json.load(error).get('detail')
        except (ValueError, AttributeError):
            detail = None
    return ValueError(f'API HTTP {error.code}: {detail or error.reason}')


def capture_farms(opener, base, key):
    request = Request(base + '/api/v1/v3/device-candidates/capture-farms', headers={'X-Ingest-Key': key})
    try:
        with opener.open(request, timeout=5) as response:
            items = json.load(response).get('items')
    except HTTPError as error:
        raise api_error(error) from error
    if not isinstance(items, list):
        raise ValueError('La API no entregó la lista de predios físicos.')
    return [(UUID(item['id']), str(item['name'])) for item in items]


def remember_farm(env_file, farm_id, replace=False):
    """Save INGEST_FARM_ID; an existing value is rewritten only when the user asked to change it."""
    text = env_file.read_text(encoding='utf-8') if env_file.is_file() else ''
    pattern = re.compile(r'(?m)^\s*INGEST_FARM_ID\s*=.*$')
    if pattern.search(text):
        if not replace:
            return False
        env_file.write_text(pattern.sub(f'INGEST_FARM_ID={farm_id}', text, count=1), encoding='utf-8', newline='\n')
        return True
    separator = '' if not text or text.endswith('\n') else '\n'
    with env_file.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(f'{separator}# Predio físico que reciben las altas USB y las detecciones LoRa.\nINGEST_FARM_ID={farm_id}\n')
    return True


def choose_farm(opener, base, key, env_file, ask=input, farms=None, replace=False):
    farms = capture_farms(opener, base, key) if farms is None else farms
    if not farms:
        raise ValueError('No hay predios físicos activos. Crea o activa un predio en GeoCattle.')
    if len(farms) == 1:
        if replace:
            remember_farm(env_file, farms[0][0], replace=True)
        return farms[0][0]
    print('Hay varios predios físicos activos. ¿A cuál pertenece el collar?')
    for number, (_, name) in enumerate(farms, 1):
        print(f'  {number}. {name}')
    while True:
        answer = ask(f'Escribe el número del predio (1-{len(farms)}): ').strip()
        if answer.isdigit() and 1 <= int(answer) <= len(farms):
            farm_id, name = farms[int(answer) - 1]
            break
        print('Número no válido.')
    if ask(f'¿Usar «{name}» también en las próximas altas y en la captura LoRa? [S/n]: ').strip().lower() in ('', 's', 'si', 'sí'):
        if remember_farm(env_file, farm_id, replace):
            print(f'Guardado en {env_file.name}. Reinicia la captura LoRa para que también lo use.')
    return farm_id


def confirm_saved_farm(opener, base, key, env_file, farm_id, ask=input):
    """Show the saved farm every time so a collar never lands in a farm the user cannot see."""
    farms = capture_farms(opener, base, key)
    name = next((name for ident, name in farms if ident == farm_id), None)
    if name is None:
        print('El predio guardado en INGEST_FARM_ID ya no está activo. Elige otro.')
        return choose_farm(opener, base, key, env_file, ask, farms, replace=True)
    if len(farms) > 1 and ask(f'El collar se registrará en «{name}». Presiona Enter para continuar o escribe c para cambiar: '
                              ).strip().lower() in ('c', 'cambiar'):
        return choose_farm(opener, base, key, env_file, ask, farms, replace=True)
    print(f'Predio: {name}')
    return farm_id


def release_direct_receiver(directory, port, ask=input):
    """A former direct T3 may become a collar; the gateway base is never reused."""
    gateway = load_profile(directory, 'gateways')
    if gateway and choose_receiver([port], gateway):
        raise ValueError('El USB identificado es la receptora base de Gateways. Conecta el collar.')
    direct = load_profile(directory, 'direct')
    if not (direct and choose_receiver([port], direct)):
        return False
    print('Esta placa estaba registrada como receptora Directa.')
    if ask('¿Usarla como collar y quitarla como receptora Directa? La recepción por Gateways no cambia [s/N]: '
           ).strip().lower() not in ('s', 'si', 'sí'):
        raise ValueError('La placa sigue registrada como receptora Directa. Conecta otro collar.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for name in ('receiver-direct.json', 'receiver.json'):
        path = Path(directory) / name
        if path.exists():
            # Se archiva, no se borra: la identidad puede restaurarse renombrando el archivo.
            path.replace(path.with_name(f'{path.stem}-retirada-{stamp}.json'))
    print('Receptora Directa retirada. Para recibir usa el modo Gateways.')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.academic')
    parser.add_argument('--farm-id', type=UUID, help='UUID del predio físico')
    args = parser.parse_args(argv)
    base = 'http://127.0.0.1:8084'
    opener = build_opener(ProxyHandler({}))
    try:
        private = load_env(args.env_file) if args.env_file.is_file() else {}
        key = private.get('INGEST_KEY') or os.environ.get('INGEST_KEY')
        if not key:
            raise ValueError('Falta INGEST_KEY en la configuración privada de captura.')
        configured_farm = private.get('INGEST_FARM_ID') or os.environ.get('INGEST_FARM_ID')
        farm_id = args.farm_id or (UUID(configured_farm) if configured_farm else None)
        with opener.open(base + '/api/v1/health', timeout=3) as response:
            if json.load(response).get('environment') != 'development':
                raise ValueError('El alta USB necesita el prototipo de desarrollo.')
        if args.farm_id is None:
            farm_id = (confirm_saved_farm(opener, base, key, args.env_file, farm_id) if farm_id
                       else choose_farm(opener, base, key, args.env_file))
        input('Deja el collar desconectado y presiona Enter. Puedes mantener conectada la receptora. ')
        before = connected_usb()
        input('Conecta solo el collar con un cable USB de datos y presiona Enter. ')
        deadline = time.monotonic() + 8
        while True:
            new_ports = [port for device, port in connected_usb().items() if device not in before]
            if new_ports or time.monotonic() >= deadline:
                break
            time.sleep(.25)
        if not new_ports:
            raise ValueError('Windows no detectó un puerto serie USB nuevo. Revisa el cable de datos y vuelve a conectar el collar.')
        if len(new_ports) > 1:
            raise ValueError('Apareció más de un puerto USB nuevo. Conecta solo el collar durante la detección.')
        selected = new_ports[0]
        release_direct_receiver(ROOT / '.runtime' / 'capture', selected)
        print(f'Leyendo {selected.device}. Un collar con firmware anterior puede tardar hasta 55 segundos.')
        descriptor = read_collar(selected.device)
        candidate = post_candidate(opener, base, descriptor, key, farm_id)
    except (OSError, ValueError, ReceiverSelectionError, EOFError) as error:
        print(f'No se pudo preparar el alta USB: {error}', file=sys.stderr)
        return 1
    url = base + '/#devices'
    print(f'Collar detectado: {candidate["hardware_id"]}. Revisa las detecciones del predio en el navegador.')
    print(url)
    webbrowser.open(url)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
