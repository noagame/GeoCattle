"""Remember a direct T3 and a gateway-base T3 without opening either port.

The profile chooses an exact USB identity. The selected mode is shared control
for the one capture process and its one archive lease; it is not a second reader.
"""
from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from adapters.serial_receiver import (
    ReceiverSelectionError, choose_receiver, load_receiver,
    receiver_record, save_receiver,
)

MODES = ('direct', 'gateways')
T3_PRODUCTS = frozenset({(0x1A86, 0x55D4)})


def normalize_mode(mode: str) -> str:
    if not isinstance(mode, str) or mode.strip().casefold() not in MODES:
        raise ReceiverSelectionError('Metodo de recepcion invalido. Utiliza direct o gateways.')
    return mode.strip().casefold()


def profile_binding_path(directory: Path, mode: str) -> Path:
    return Path(directory) / ('receiver-' + normalize_mode(mode) + '.json')


def load_profile(directory: Path, mode: str) -> dict[str, Any] | None:
    """The old binding remains a read-only fallback for the direct method."""
    mode = normalize_mode(mode)
    path = profile_binding_path(directory, mode)
    if mode == 'direct' and not path.exists():
        path = Path(directory) / 'receiver.json'
    return load_receiver(path)


def _same_receiver(first: Any, second: Mapping[str, Any]) -> bool:
    return choose_receiver([first], second) is not None


def save_profile(directory: Path, mode: str, port: Any) -> dict[str, Any]:
    mode = normalize_mode(mode)
    record = receiver_record(port)
    other_mode = 'gateways' if mode == 'direct' else 'direct'
    other = load_profile(directory, other_mode)
    if other is not None and _same_receiver(record, other):
        raise ReceiverSelectionError(
            'Esta identidad USB ya pertenece al otro metodo de recepcion. '
            'Los perfiles direct y gateways deben usar placas distintas.'
        )
    return save_receiver(profile_binding_path(directory, mode), port)


def preferred_mode(directory: Path) -> str:
    path = Path(directory) / 'receiver-mode.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return 'direct'
    except (OSError, ValueError) as error:
        raise ReceiverSelectionError('No se pudo leer receiver-mode.json; vuelve a seleccionar el metodo.') from error
    if (not isinstance(value, dict) or set(value) != {'version', 'mode'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ReceiverSelectionError('receiver-mode.json no tiene un formato admitido.')
    return normalize_mode(value['mode'])


def select_mode(directory: Path, mode: str) -> str:
    """Atomically replace only the mode control file, preserving all readings."""
    mode = normalize_mode(mode)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'receiver-mode.json'
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.' + path.name + '.', suffix='.tmp', dir=directory,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            json.dump({'version': 1, 'mode': mode}, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return mode


def candidates_for_mode(ports: Any, directory: Path, mode: str) -> list[Any]:
    """Filter metadata by profile, never probing a XIAO or another method.

    Unbound profiles admit only the current T3 CH9102 product and exclude the
    other method's identity. A stored identity survives COM/location changes.
    """
    mode = normalize_mode(mode)
    remembered = load_profile(directory, mode)
    other_mode = 'gateways' if mode == 'direct' else 'direct'
    other = load_profile(directory, other_mode)
    if remembered is not None and other is not None and _same_receiver(remembered, other):
        raise ReceiverSelectionError('Ambos metodos tienen la misma identidad USB; revisa sus perfiles.')
    candidates = []
    for port in ports:
        try:
            record = receiver_record(port)
        except ReceiverSelectionError:
            continue
        if remembered is not None:
            if _same_receiver(port, remembered):
                candidates.append(port)
        elif ((record['vid'], record['pid']) in T3_PRODUCTS
              and (other is None or not _same_receiver(port, other))):
            candidates.append(port)
    return candidates


def choose_profile_receiver(ports: Any, directory: Path, mode: str,
                            requested: str = 'auto') -> Any | None:
    """A manual COM narrows the profile; it never reassigns a saved identity."""
    mode = normalize_mode(mode)
    candidates = candidates_for_mode(ports, directory, mode)
    return choose_receiver(candidates, load_profile(directory, mode), requested)
