"""Normaliza el protocolo físico JSON V5 compacto al contrato API existente."""
import json
import math
import re


def decode_json(text, received_at, radio=None, receiver='PC-COM5'):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Clave JSON duplicada')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('JSON no finito')

    if len(text.encode('utf-8')) > 1024:
        raise ValueError('Linea JSON excesiva')
    message = json.loads(text, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    if not isinstance(message, dict):
        raise ValueError('Objeto JSON requerido')
    if 'packet' in message:
        if set(message) != {'packet', 'radio'} or not isinstance(message['packet'], dict) or not isinstance(message['radio'], dict):
            raise ValueError('Sobre de receptor invalido')
        radio = message['radio']
        message = message['packet']
    required = {'v', 'id', 's', 'q', 'u', 'g', 't', 'a', 'm', 'b', 'p', 'f', 'e'}
    if not required <= set(message) or set(message) - required - {'d'}:
        raise ValueError('Campos JSON V5 invalidos')
    if type(message['v']) is not int or message['v'] != 5:
        raise ValueError('Version JSON no admitida')
    if not isinstance(message['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}', message['id']):
        raise ValueError('Identidad V5 invalida')
    if not isinstance(message['s'], str) or not re.fullmatch(r'[0-9A-Fa-f]{16}', message['s']):
        raise ValueError('Sesion V5 invalida')

    def arr(key, size):
        value = message[key]
        if not isinstance(value, list) or len(value) != size:
            raise ValueError('Vector JSON invalido: ' + key)
        return value

    def whole(value, low, high):
        if type(value) is not int or not low <= value <= high:
            raise ValueError('Entero JSON invalido')
        return value

    def measurement(value, low, high):
        if value is None:
            return None
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Medicion JSON invalida')
        return value

    whole(message['q'], 0, 2**32 - 1)
    whole(message['u'], 0, 2**32 - 1)
    whole(message['p'], 30000, 40000)
    whole(message['f'], 0, 7)
    reason = whole(message['e'], 0, 2)
    lat, lon, age, sats, hdop = arr('g', 5)
    lat = measurement(lat, -90, 90)
    lon = measurement(lon, -180, 180)
    if (lat is None) != (lon is None):
        raise ValueError('Coordenadas incompletas')
    fix = lat is not None
    age = whole(age, -1, 2**32 - 1)
    sats = whole(sats, -1, 99)
    hdop = measurement(hdop, 0, 999.99)
    if fix and not 0 <= age < 5000:
        raise ValueError('Posicion JSON vencida')
    axes = [measurement(x, -32, 32) for x in arr('a', 3)]
    temp = measurement(message['t'], -60, 100)
    state, score = arr('m', 2)
    state = whole(state, -1, 1)
    score = measurement(score, 0, 100)
    if (state != -1 and score is None) or (state != -1 and any(x is None for x in axes)):
        raise ValueError('Movimiento sin acelerometro valido')
    battery = arr('b', 5)
    for i, value in enumerate(battery):
        whole(value, -1, (4350, 100, 1, 1, 1)[i])
    expected_flags = (0 if fix else 1) | (2 if temp is None else 0) | (4 if any(x is None for x in axes) else 0)
    if message['f'] != expected_flags:
        raise ValueError('Flags JSON inconsistentes')
    diagnostics = message.get('d')
    if diagnostics is not None:
        if not isinstance(diagnostics, list) or len(diagnostics) != 3:
            raise ValueError('Diagnostico GPS invalido')
        for value in diagnostics:
            whole(value, 0, 2**32 - 1)
    if radio is not None:
        if not isinstance(radio, dict) or set(radio) != {'rssi_dbm', 'snr_db'}:
            raise ValueError('Radio JSON invalida')
        radio = {'rssi_dbm': measurement(radio['rssi_dbm'], -200, 20),
                 'snr_db': measurement(radio['snr_db'], -100, 100)}
        if any(x is None for x in radio.values()):
            raise ValueError('Radio JSON sin valores')
    n = lambda v: 'nan' if v is None else str(v)
    fields = ['4', message['id'], message['s'], str(message['q']), 'device', str(message['u']),
              str(int(fix)), str(age), n(lat), n(lon), n(temp), *map(n, axes), n(score),
              str(message['f']), str(message['p']), *map(str, battery[:4])]
    from .lora_usb import decode
    payload, _ = decode(','.join(fields), received_at, radio, receiver)
    payload['quality'].update(wire_protocol_version=5, gps_satellites=None if sats == -1 else sats,
                              gps_hdop=hdop, movement_state={-1: 'unknown', 0: 'rest', 1: 'moving'}[state],
                              activity_method='highpass_rms_1s_g', usb_present=None if battery[4] == -1 else bool(battery[4]),
                              tx_reason=('boot', 'periodic', 'movement_start')[reason])
    if diagnostics is not None:
        payload['quality']['gps_diagnostics'] = dict(zip(('bytes', 'valid_sentences', 'failed_checksums'), diagnostics))
    wire = json.dumps(message, sort_keys=True, separators=(',', ':'), allow_nan=False)
    # Limite de radio para el objeto original, no para el sobre USB de RSSI/SNR.
    if len(json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) > 255:
        raise ValueError('Paquete JSON supera 255 bytes LoRa')
    return payload, wire
