#!/usr/bin/env python3
"""Empaqueta el árbol de trabajo para subirlo a un servidor sin Git.

Toma los archivos versionados y los nuevos que Git no ignora, con finales de
línea LF. Rechaza configuraciones privadas, archivos de ejecución, respaldos,
colas y enlaces que Git incluya en la selección. Por defecto deja solo lo que
usa el servidor (Compose, imágenes, migraciones, scripts del servidor y la guía)
y un AGENTS.md propio; --completo incluye todo el árbol.

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
# Lo que el servidor construye o ejecuta: compose*.yaml, backend/Dockerfile, infrastructure/*.Dockerfile.
SERVER_FILES = {
    '.dockerignore', '.env.example', 'compose.yaml', 'compose.cloudflare.yaml', 'compose.mirror.yaml',
    'backend/Dockerfile', 'backend/pyproject.toml', 'backend/requirements.lock',
    'adapters/requirements.txt', 'infrastructure/nginx.conf', 'infrastructure/web.Dockerfile',
    'scripts/configure.py', 'scripts/docker_project.py', 'scripts/mirror.py',
    'docs/DESPLIEGUE_SERVIDOR_ESPEJO.md',
}
SERVER_FOLDERS = ('backend/geocattle/', 'adapters/', 'database/migrations/', 'infrastructure/espejo-ssh/',
                  'frontend/')
SERVER_SKIP = ('frontend/tests/',)
SERVER_AGENTS = """# GeoCattle · servidor espejo

Este paquete contiene solo lo que el servidor necesita para publicar la web de GeoCattle como copia del PC del campo.

Sigue la **Parte A** de [docs/DESPLIEGUE_SERVIDOR_ESPEJO.md](docs/DESPLIEGUE_SERVIDOR_ESPEJO.md), en orden, y respeta sus reglas:

- No edites el código, los `compose*.yaml` ni `scripts/`. Si algo falla, informa el error tal cual al dueño del PC.
- No borres volúmenes ni regeneres las llaves SSH del host.
- No crees cuentas de GeoCattle: llegan del PC cuando el dueño ejecuta `pc-connect`.
- Los secretos de `.env.pilot` y el token de Cloudflare nunca se escriben en el chat, en registros ni en tickets.
"""


def server_file(name):
    if name in SERVER_FILES:
        return True
    if name.startswith(SERVER_SKIP) or name.endswith('.md'):
        return False
    return name.startswith(SERVER_FOLDERS)


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


def build(output_dir, full=False):
    names = list(tracked_files())
    extra = {}
    if not full:
        names = [name for name in names if server_file(name)]
        extra['AGENTS.md'] = SERVER_AGENTS.encode('utf-8')
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
        for name, data in extra.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            count += 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output_dir / f'{target.name}.sha256').write_text(f'{digest}  {target.name}\n', encoding='utf-8', newline='\n')
    return target, count, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--salida', type=Path, default=ROOT.parent / 'GeoCattle-Despliegue' / 'paquete')
    parser.add_argument('--completo', action='store_true', help='Incluye todo el árbol, no solo lo del servidor')
    args = parser.parse_args()
    target, count, digest = build(args.salida, args.completo)
    print(f'{count} archivos en {target}')
    print(f'SHA-256 {digest}')


if __name__ == '__main__':
    main()
