"""USB receiver identity and an exclusive capture lease.

This module enumerates metadata only. It never opens a serial device, resets a
board, sends commands, reads telemetry, or touches the application database.
A USB VID/PID identifies a product, not a particular T3: remembered devices also
need an exact serial number, or an exact location when neither has a serial.
"""
from collections.abc import Mapping
import errno
import json
import os
from pathlib import Path
import tempfile
from typing import Any


class ReceiverSelectionError(RuntimeError):
    """A safe receiver choice requires an explicit user selection."""


class CaptureAlreadyRunning(RuntimeError):
    """Another capture holds the lease for this archive directory."""


def enumerate_ports() -> list[Any]:
    """Return pyserial port metadata, without opening any serial devices."""
    from serial.tools import list_ports
    return sorted(list(list_ports.comports()), key=lambda port: str(port.device).casefold())


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _usb_number(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 65535


def _usb_port(port: Any) -> bool:
    # Bluetooth COM ports have no USB VID/PID; descriptions are never evidence.
    return bool(_text(_field(port, 'device')) and _usb_number(_field(port, 'vid'))
                and _usb_number(_field(port, 'pid')))


def receiver_record(port: Any) -> dict[str, Any]:
    """Build a version-1 binding from a selected USB port's identity metadata.

    Reject a product-only binding: it could silently select a different board.
    The saved COM name is informational; remembered matching never relies on it.
    """
    if not _usb_port(port):
        raise ReceiverSelectionError('El puerto elegido no tiene identidad USB. Indica la T3 receptora con -Puerto COMx.')
    serial = _text(_field(port, 'serial_number'))
    location = _text(_field(port, 'location'))
    if not serial and not location:
        raise ReceiverSelectionError('No se puede recordar esta placa: falta numero de serie y ubicacion USB. Usa -Puerto COMx explicitamente.')
    return {'version': 1, 'device': _text(_field(port, 'device')),
            'vid': _field(port, 'vid'), 'pid': _field(port, 'pid'),
            'serial_number': serial, 'location': location}


def identity(port: Any) -> dict[str, Any]:
    """Public alias for the canonical, safely rememberable receiver record."""
    return receiver_record(port)


def _remembered_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get('version', 1) != 1:
        raise ReceiverSelectionError('receiver.json no tiene un formato admitido. Vuelve a elegir la T3 con -Puerto COMx.')
    # The historical COM name can be absent; identity fields are authoritative.
    candidate = dict(value)
    candidate['device'] = _text(value.get('device')) or 'recordado'
    return receiver_record(candidate)


def choose_receiver(ports: Any, remembered: Mapping[str, Any] | None,
                    requested: str = 'auto') -> Any | None:
    """Select one USB metadata object, or None while that receiver is absent.

    Explicit requested device names override a remembered binding and never fall
    back to another port. Auto mode honors a remembered serial/VID/PID; only if
    the saved serial is absent can an equally serial-less device match location.
    Without a binding, a single USB port is an initial selection. More than one
    candidate, including duplicated identities, is an actionable error.
    Selection does not persist a binding: call save_receiver after confirming it.
    """
    candidates = [port for port in ports if _usb_port(port)]
    requested = str(requested or 'auto').strip()
    if requested and requested.casefold() != 'auto':
        names = {requested.casefold()}
        if requested.startswith('/dev/'):
            names.add(os.path.realpath(requested).casefold())
        matches = [port for port in candidates
                   if _text(_field(port, 'device')).casefold() in names]
    elif remembered is not None:
        identity = _remembered_record(remembered)
        product_matches = [port for port in candidates
                           if _field(port, 'vid') == identity['vid']
                           and _field(port, 'pid') == identity['pid']]
        if identity['serial_number']:
            matches = [port for port in product_matches
                       if _text(_field(port, 'serial_number')) == identity['serial_number']]
        else:
            matches = [port for port in product_matches
                       if _text(_field(port, 'serial_number')) is None
                       and _text(_field(port, 'location')) == identity['location']]
    else:
        matches = candidates
    if len(matches) > 1:
        names = ', '.join(sorted(str(_field(port, 'device')) for port in matches))
        raise ReceiverSelectionError('Hay varias placas USB compatibles (' + names + '). No se eligio ninguna. Usa -Puerto COMx para indicar la T3 receptora.')
    return matches[0] if matches else None


def load_receiver(path: Path) -> dict[str, Any] | None:
    """Read/validate a binding. A missing file means no initial binding yet."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as error:
        raise ReceiverSelectionError('No se pudo leer receiver.json. Revisa el archivo o vuelve a indicar -Puerto COMx.') from error
    return _remembered_record(value)


def save_receiver(path: Path, port: Any) -> dict[str, Any]:
    """Atomically replace a binding with the selected port's metadata.

    Writes and fsyncs a unique sibling temporary file, then os.replace. A failed
    replace leaves the previous binding intact and removes the temporary file.
    """
    path = Path(path)
    record = receiver_record(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            json.dump(record, output, ensure_ascii=True, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return record


class CaptureLease:
    """Nonblocking OS lease for one capture archive directory.

    Use ``with CaptureLease(directory):`` around the entire capture lifetime,
    before archive initialization, background threads, and status-file writes.
    The open handle keeps the OS lock alive. The lock file remains after release;
    its existence alone never means a process is running, and it is not deleted.
    """
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'capture.lock'
        self._stream = None

    def acquire(self) -> 'CaptureLease':
        if self._stream is not None:
            return self
        self.directory.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            # Windows byte-range locking needs one existing byte and position 0.
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(error, 'winerror', None) in (32, 33):
                    raise CaptureAlreadyRunning('Ya hay un capturador de GeoCattle usando esta carpeta. Utiliza la instancia existente.') from error
                raise
        except BaseException:
            stream.close()
            raise
        self._stream = stream
        return self

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self) -> 'CaptureLease':
        return self.acquire()

    def __exit__(self, exception_type, exception, traceback) -> bool:
        self.release()
        return False
