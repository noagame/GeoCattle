"""Identifica un gateway GeoCattle por USB y lo configura con un nodo reservado."""
import argparse
from getpass import getpass
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.register_collar_usb import api_error, capture_farms, connected_usb, remember_farm
from adapters.lora_usb import load_env
from adapters.receiver_profiles import MODES, T3_PRODUCTS, load_profile
from adapters.serial_receiver import ReceiverSelectionError, choose_receiver

BASE = 'http://127.0.0.1:8084'
API = BASE + '/api/v1'
ENDPOINT = '/v3/gateway-candidates'
MAX_LINE = 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, status, message, headers, new_url):
        return None


def request_json(opener, path, body=None, **headers):
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = Request(API + path, data=data, headers={'Content-Type': 'application/json', **headers})
    try:
        with opener.open(request, timeout=8) as response:
            return None if response.status == 204 else json.load(response)
    except HTTPError as error:
        raise api_error(error) from error


def select_farm(farms, configured, args, ask=input):
    names = dict(farms)
    if args.farm_id:
        if args.farm_id not in names:
            raise ValueError('El predio indicado no está disponible para captura.')
        farm_id = args.farm_id
    elif configured in names and (len(farms) == 1 or ask(
            f'Predio guardado: {names[configured]}. Enter para usarlo o c para cambiar: ').strip().lower() != 'c'):
        farm_id = configured
    elif len(farms) == 1:
        farm_id = farms[0][0]
    else:
        if not farms:
            raise ValueError('No hay predios físicos activos.')
        if configured:
            print('El predio guardado ya no está disponible o se solicitó cambiarlo.')
        for index, (_, name) in enumerate(farms, 1):
            print(f'  {index}. {name}')
        choice = ask('Selecciona el número del predio del gateway: ').strip()
        if not choice.isascii() or not choice.isdigit() or not 1 <= int(choice) <= len(farms):
            raise ValueError('Número de predio no válido.')
        farm_id = farms[int(choice) - 1][0]
        if ask('¿Recordar este predio para próximas capturas? [s/N]: ').strip().lower() in ('s', 'sí', 'si'):
            remember_farm(args.env_file, farm_id, replace=configured is not None)
    print(f'Predio: {names[farm_id]}')
    return farm_id


def login(opener, farm_id):
    session = request_json(opener, '/auth/login', {'username': input('Usuario de GeoCattle: ').strip(),
                                                   'password': getpass('Contraseña de GeoCattle: ')})
    if session.get('mfa_required'):
        if session.get('setup_required'):
            raise ValueError('Completa la inscripción MFA en la web antes de usar la terminal.')
        session = request_json(opener, '/auth/mfa/verify', {'challenge_token': session['challenge_token'],
                                                           'code': getpass('Código del autenticador: ').strip()})
    csrf = {'X-CSRF-Token': session['csrf_token']}
    if session['user']['farm_id'] != str(farm_id):
        session = request_json(opener, '/auth/context', {'farm_id': str(farm_id)}, **csrf)
    if session['user']['role'] not in ('owner', 'admin') or session['user']['farm_id'] != str(farm_id):
        raise ValueError('Se requiere una sesión de dueño o administrador de este predio.')
    return {'X-CSRF-Token': session['csrf_token']}


def reject_receiver(directory, port):
    for mode in MODES:
        profile = load_profile(directory, mode)
        if profile and choose_receiver([port], profile):
            raise ValueError('Este USB pertenece a una receptora registrada. Conecta el gateway XIAO.')
    if (port.vid, port.pid) in T3_PRODUCTS:
        raise ValueError('Esta placa usa el USB de una T3 receptora. Conecta el gateway XIAO.')


def select_port():
    input('Deja el gateway desconectado y presiona Enter. No desconectes la receptora. ')
    before = connected_usb()
    input('Conecta solo el gateway con un cable USB de datos y presiona Enter. ')
    deadline = time.monotonic() + 8
    while True:
        added = [port for device, port in connected_usb().items() if device not in before]
        if len(added) == 1:
            reject_receiver(ROOT / '.runtime' / 'capture', added[0])
            return added[0].device
        if len(added) > 1:
            raise ValueError('Aparecieron varios puertos. Conecta un solo gateway.')
        if time.monotonic() >= deadline:
            raise ValueError('No se encontró un puerto USB nuevo. Comprueba el cable de datos.')
        time.sleep(.25)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Clave duplicada en el descriptor')
        result[key] = value
    return result


def parse_usb_line(line):
    try:
        item = json.loads(line, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(item, dict):
        return None
    kind = item.get('type')
    if kind in ('geocattle_collar', 'geocattle_receiver') or 'gc_bus' in item or {'packet', 'radio'} <= item.keys():
        raise ValueError('Se detectó un collar o una receptora, no un gateway.')
    if type(item.get('version')) is not int or item['version'] != 1:
        return None
    if kind == 'geocattle_gateway_error' and item.get('error') == 'nvs':
        raise ValueError('El gateway no pudo guardar el nodo en su memoria.')
    eui, node = item.get('gateway_eui'), item.get('node_id')
    if not isinstance(eui, str) or re.fullmatch('[0-9a-f]{16}', eui) is None:
        return None
    if 'node_id' not in item or (node is not None and (type(node) is not int or node not in (0, 1, 2))):
        return None
    node = node or None
    if item.get('provisioned') is not (node is not None):
        return None
    firmware = item.get('firmware')
    if kind == 'geocattle_gateway' and isinstance(firmware, str) and firmware.strip() and len(firmware) <= 100:
        return kind, {'gateway_eui': eui, 'node_id': node, 'firmware': firmware}
    if kind == 'geocattle_gateway_node' and node is not None:
        return kind, {'gateway_eui': eui, 'node_id': node}
    return None


def serial_exchange(link, command, accept, timeout=12):
    limit = time.monotonic() + timeout
    next_query = 0
    line = bytearray()
    while time.monotonic() < limit:
        now = time.monotonic()
        if now >= next_query:
            link.write(f'\n{command}\n'.encode('ascii'))
            next_query = now + 1
        for byte in link.read(min(link.in_waiting or 1, MAX_LINE)):
            if byte == 10:
                if len(line) <= MAX_LINE and (reply := parse_usb_line(line)) and accept(*reply):
                    return reply[1]
                line.clear()
            elif len(line) <= MAX_LINE:
                line.append(byte)
    raise ValueError('El gateway no respondió. Verifica el firmware, o reconecta la misma placa para reintentar el nodo reservado.')


def enroll(link, opener, csrf, candidate, descriptor):
    path = f'{ENDPOINT}/{candidate["id"]}'
    allocation = request_json(opener, f'{path}/reserve', {}, **csrf)
    node = allocation.get('reserved_node_id')
    eui = descriptor['gateway_eui']
    if type(node) is not int or node not in (1, 2) or allocation.get('gateway_eui') != eui:
        raise ValueError('La API no confirmó la reserva para el gateway conectado.')
    if descriptor['node_id'] not in (None, node):
        raise ValueError('La placa informa otro nodo. No se modificó el gateway.')
    name = input(f'Nombre [Gateway {node:02d}]: ').strip()
    confirmed = serial_exchange(link, f'GEOCATTLE_SET_NODE_V1 {eui} {node}',
                                lambda kind, data: kind == 'geocattle_gateway_node' and data['node_id'] == node
                                and data['gateway_eui'] == eui)
    payload = {'confirmed_node_id': confirmed['node_id'], 'confirmed_eui': eui}
    if name:
        payload['name'] = name
    return request_json(opener, f'{path}/approve', payload, **csrf)['gateway']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.academic')
    parser.add_argument('--farm-id', type=UUID, help='UUID del predio físico')
    parser.add_argument('--solo-detectar', action='store_true', help='Usa la clave de captura y deja la aprobación para la web')
    args = parser.parse_args(argv)
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(CookieJar()))
    csrf = None
    try:
        if request_json(opener, '/health').get('environment') != 'development':
            raise ValueError('El asistente USB requiere el prototipo de desarrollo en localhost:8084.')
        private = load_env(args.env_file) if args.env_file.is_file() else {}
        key = private.get('INGEST_KEY') or os.environ.get('INGEST_KEY')
        if not key:
            raise ValueError('Falta INGEST_KEY en la configuración privada de captura.')
        configured = private.get('INGEST_FARM_ID') or os.environ.get('INGEST_FARM_ID')
        farm = select_farm(capture_farms(opener, BASE, key), UUID(configured) if configured else None, args)
        if not args.solo_detectar:
            csrf = login(opener, farm)
        import serial
        with serial.Serial(select_port(), baudrate=115200, timeout=.25, write_timeout=1) as link:
            descriptor = serial_exchange(link, 'GEOCATTLE_IDENTIFY_V1', lambda kind, data: kind == 'geocattle_gateway')
            headers = csrf or {'X-Ingest-Key': key, 'X-Farm-ID': str(farm)}
            candidate = request_json(opener, ENDPOINT, descriptor, **headers)
            if csrf:
                gateway = enroll(link, opener, csrf, candidate, descriptor)
                print(f'Instalado: {gateway["name"]} · nodo {gateway["node_id"]:02d} · {descriptor["gateway_eui"]}')
            else:
                print(f'Detección pendiente: {descriptor["gateway_eui"]}. Abre la bandeja Gateways detectados para aprobarla.')
        webbrowser.open(BASE + '/#gateways')
        return 0
    except (OSError, ValueError, ReceiverSelectionError, EOFError, KeyboardInterrupt) as error:
        print(f'No se completó el alta USB: {error}', file=sys.stderr)
        return 1
    finally:
        if csrf:
            try:
                request_json(opener, '/auth/logout', {}, **csrf)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    raise SystemExit(main())
