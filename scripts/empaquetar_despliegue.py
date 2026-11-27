#!/usr/bin/env python3
"""Empaqueta el árbol de trabajo para subirlo a un servidor sin Git.

Incluye los archivos versionados y los nuevos que Git no ignora, con finales de
línea LF. Rechaza configuraciones privadas, archivos de ejecución, respaldos,
colas y enlaces que Git incluya en la selección.

  python scripts/empaquetar_despliegue.py
  scp ../GeoCattle-Despliegue/paquete/geocattle-*.tar.gz* usuario@servidor:/tmp/
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {'config.h'}  # firmware/GeoCattle_Nube_T3/config.h


def tracked_files():
    output = subprocess.run(['git', 'ls-files', '-z', '-co', '--exclude-standard'], cwd=ROOT,
                            check=True, capture_output=True).stdout
    for name in sorted(set(output.decode('utf-8').split('\0')) - {''}):
        path = PurePosixPath(name)
        parts = [part.casefold() for part in path.parts]
        if any(part.startswith('.env') for part in parts) and path.parts != ('.env.example',):
            raise SystemExit(f'Archivo privado no ignorado: {name}. Agrégalo a .gitignore.')
        if parts[-1] in PRIVATE_NAMES:
            continue
        if {'.runtime', 'backups'}.intersection(parts) or parts[-1].endswith('.sqlite3') or '.sqlite3-' in parts[-1]:
            raise SystemExit(f'Archivo de ejecución o respaldo incluido por Git: {name}.')
        source = ROOT / name
        if source.resolve() != source:
            raise SystemExit(f'El paquete requiere archivos sin enlaces: {name}.')
        if source.is_file():
            yield name


def normalized(data):
    if b'\0' in data[:8192]:
        return data
    return data.replace(b'\r\n', b'\n')


def build(output_dir):
    names = list(tracked_files())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f'geocattle-{stamp}.tar.gz'
    count = 0
    with tarfile.open(target, 'w:gz', format=tarfile.PAX_FORMAT) as archive:
        for name in names:
            data = normalized((ROOT / name).read_bytes())
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            info.mode = 0o755 if name.endswith('.sh') else 0o644
            archive.addfile(info, io.BytesIO(data))
            count += 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output_dir / f'{target.name}.sha256').write_text(f'{digest}  {target.name}\n', encoding='utf-8', newline='\n')
    return target, count, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--salida', type=Path, default=ROOT.parent / 'GeoCattle-Despliegue' / 'paquete')
    args = parser.parse_args()
    target, count, digest = build(args.salida)
    print(f'{count} archivos en {target}')
    print(f'SHA-256 {digest}')


if __name__ == '__main__':
    main()
