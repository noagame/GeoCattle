"""USB bus V1 -> existing per-reading V4/V5 capture contract.

This module does not open a serial port, acknowledge radio reception or write
to the database. The capture process archives the original USB line first.
Gateway delay is an estimate, not a timestamp supplied by a synchronized clock.
"""
from dataclasses import dataclass
from datetime import timedelta
import json
import re

MAX_USB_LINE_BYTES = 8192
MAX_BATCH_READINGS = 4
MAX_TRANSPORT_DELAY_MS = 1_800_000


@dataclass(frozen=True)
class ReadingError:
    index: int
    reason: str


@dataclass(frozen=True)
class DecodedLine:
    readings: tuple
    errors: tuple = ()
    is_bus: bool = False
    batch: str | None = None


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Clave JSON duplicada')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('JSON no finito')


def _whole(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Entero de transporte invalido')
    return value


def _transport(value):
    required = {'delay_ms', 'origin_gateway', 'hops', 'path'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Metadatos de transporte invalidos')
    delay = _whole(value['delay_ms'], 0, MAX_TRANSPORT_DELAY_MS)
    origin = _whole(value['origin_gateway'], 0, 2)
    hops = _whole(value['hops'], 0, 2)
    path = _whole(value['path'], 0, 6)
    if path not in (0, 2, 4, 6) or hops != path.bit_count():
        raise ValueError('Ruta y numero de saltos inconsistentes')
    if origin == 0:
        if path != 0 or hops != 0:
            raise ValueError('Recepcion directa con ruta de gateway')
    elif not path & (1 << origin):
        raise ValueError('Gateway de origen ausente en la ruta')
    return {'delay_ms': delay, 'origin_gateway': origin,
            'hops': hops, 'path': path}


def decode_many(line, received_at, radio=None, receiver='PC-COM5'):
    """Decode individual legacy frames or a bus of at most four readings.

    A malformed outer envelope rejects the complete line. Individual malformed
    readings are returned as errors while valid siblings remain available.
    Callers must log ``errors``; the raw line remains their recovery evidence.
    """
    if len(line.encode('utf-8')) > MAX_USB_LINE_BYTES:
        raise ValueError('Linea USB excesiva')
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError('Fecha de recepcion requiere zona horaria')
    text = line.strip()
    if text.startswith('Contenido:'):
        text = text.split(':', 1)[1].strip()
    message = None
    if text.startswith('{'):
        message = json.loads(text, object_pairs_hook=_unique_keys,
                             parse_constant=_invalid_constant)
    if not isinstance(message, dict) or 'gc_bus' not in message:
        # Lazy import avoids the lora_json -> lora_usb compatibility cycle.
        from adapters.lora_usb import decode
        item = decode(line, received_at, radio, receiver)
        return DecodedLine((item,) if item else ())
    required = {'gc_bus', 'receiver', 'batch', 'readings'}
    if set(message) != required or type(message['gc_bus']) is not int or message['gc_bus'] != 1:
        raise ValueError('Version o sobre de bus USB invalido')
    if not isinstance(message['receiver'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', message['receiver']):
        raise ValueError('Identidad de base invalida')
    if not isinstance(message['batch'], str) or not re.fullmatch(r'[0-9A-Fa-f]{8}-[0-9]{1,10}', message['batch']):
        raise ValueError('Identidad de lote invalida')
    _whole(int(message['batch'].split('-')[1]), 0, 2**32 - 1)
    records = message['readings']
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH_READINGS:
        raise ValueError('Bus USB requiere entre una y cuatro lecturas')
    from adapters.lora_json import decode_json
    readings, errors = [], []
    for index, record in enumerate(records, 1):
        try:
            if not isinstance(record, dict) or set(record) != {'packet', 'radio', 'transport'}:
                raise ValueError('Lectura de bus invalida')
            transport = _transport(record['transport'])
            estimated_at = received_at - timedelta(milliseconds=transport['delay_ms'])
            original = json.dumps({'packet': record['packet'], 'radio': record['radio']},
                                  allow_nan=False, separators=(',', ':'))
            payload, canonical_wire = decode_json(original, estimated_at, receiver=receiver)
            payload['quality'].update(
                time_basis='pc_reception_minus_gateway_delay',
                observed_at_estimated=True,
                capture_received_at=received_at.isoformat(),
                transport={**transport, 'estimated': True,
                           'bus_version': 1, 'batch': message['batch'],
                           'base_receiver': message['receiver'],
                           'pc_received_at': received_at.isoformat(),
                           'radio_scope': 'collar_to_first_receiver'},
            )
            readings.append((payload, canonical_wire))
        except (ValueError, TypeError, OverflowError) as error:
            errors.append(ReadingError(index, str(error)))
    return DecodedLine(tuple(readings), tuple(errors), is_bus=True, batch=message['batch'])
