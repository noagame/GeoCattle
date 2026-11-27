"""Configura la T3 base por USB. Las claves se escriben solo en la memoria de la placa."""
import argparse
from getpass import getpass
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID


def exchange(connection, command, action, eui=None, value=None):
    fields = [command]
    if eui:
        fields.append(eui)
    if value is not None:
        fields.append(value)
    wire = (' '.join(fields) + '\n').encode()
    if len(wire) >= 6144:
        raise ValueError('La configuración excede la longitud USB admitida.')
    connection.write(wire)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        raw = connection.read_until(b'\n', 8192)
        if not raw.startswith(b'#GC_CLOUD '):
            continue
        try:
            reply = json.loads(raw.removeprefix(b'#GC_CLOUD '))
        except (UnicodeError, ValueError):
            continue
        if not isinstance(reply, dict) or reply.get('version') != 1:
            continue
        if reply.get('action') in (action, 'identity'):
            if not reply.get('ok') or (eui and reply.get('eui') != eui):
                raise ValueError(f'La placa rechazó la operación {action}. Verifica el EUI y el estado del búfer.')
            return reply
    raise ValueError(f'La placa no respondió a {action}. Verifica el puerto, el firmware y la captura local.')


def cloud_config(ca_path):
    origin = input('Origen HTTPS de GeoCattle: ').strip().rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or re.search(r'[\s\\]', origin)):
        raise ValueError('Indica el origen HTTPS público de GeoCattle.')
    ca = ca_path.read_text(encoding='ascii').strip() + '\n'
    if not ca.startswith('-----BEGIN CERTIFICATE-----') or len(ca) > 3900:
        raise ValueError('Indica la CA de confianza en formato PEM, hasta 3900 bytes.')
    farm = str(UUID(input('UUID del predio de producción: ').strip()))
    key = getpass('INGEST_KEY: ')
    access_id = getpass('ID de Cloudflare Access (Enter para omitir): ')
    access_secret = getpass('Secreto de Cloudflare Access: ') if access_id else ''
    if len(key) < 32 or bool(access_id) != bool(access_secret):
        raise ValueError('Usa una clave de ingesta de al menos 32 caracteres y las dos partes del token.')
    return dict(url=origin, farm=farm, key=key, access_id=access_id, access_secret=access_secret, ca=ca)


def wifi_config():
    networks = []
    for number in range(1, 4):
        ssid = input(f'SSID {number} (Enter para terminar): ').strip()
        if not ssid:
            break
        networks.append({'ssid': ssid, 'password': getpass(f'Contraseña WiFi {number}: ')})
    if not networks:
        raise ValueError('Ingresa al menos una red WiFi.')
    return networks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--eui', help='EUI confirmado de la T3 base')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--time-only', action='store_true')
    mode.add_argument('--ca-cert', type=Path, help='Provisionar red y nube con la CA raíz PEM indicada')
    parser.add_argument('--initialize-buffer', action='store_true',
                        help='Inicializar LittleFS cuando aún no se puede montar')
    args = parser.parse_args()
    if not args.status and not re.fullmatch('[0-9A-Fa-f]{12}', args.eui or ''):
        parser.error('Consulta --status y confirma el EUI de la placa con --eui')
    if args.ca_cert and not sys.stdin.isatty():
        parser.error('Ejecuta la provisión en una consola interactiva para proteger las claves')
    import serial
    try:
        eui = args.eui.upper() if args.eui else None
        with serial.Serial(args.port, 115200, timeout=0.5, write_timeout=3) as connection:
            identity = exchange(connection, 'GEOCATTLE_CLOUD_IDENTIFY_V1', 'identify')
            if eui and identity.get('eui') != eui:
                raise ValueError('El puerto corresponde a otra T3.')
            if args.status:
                print(json.dumps(identity, ensure_ascii=False))
                return 0
            if args.ca_cert:
                cloud = cloud_config(args.ca_cert)
                wifi = wifi_config()
                if args.initialize_buffer:
                    exchange(connection, 'GEOCATTLE_INIT_CLOUD_BUFFER_V1', 'buffer', eui)
                elif not identity.get('buffer_ready'):
                    raise ValueError('LittleFS no montado. Usa --initialize-buffer al preparar una placa nueva.')
                exchange(connection, 'GEOCATTLE_SET_CLOUD_V1', 'cloud', eui, json.dumps(cloud))
                exchange(connection, 'GEOCATTLE_SET_WIFI_V1', 'wifi', eui, json.dumps(wifi, ensure_ascii=False))
            exchange(connection, 'GEOCATTLE_SET_TIME_V1', 'time', eui, str(int(time.time())))
            print(f'T3 base {eui} actualizada.')
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
