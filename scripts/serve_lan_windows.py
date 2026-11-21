"""Serve the existing Windows prototype over HTTPS on a local IPv4 address."""
import argparse
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Network
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from prototype_windows import ROOT, environment, listening


PORT = 8445
LOCAL_NETWORKS = tuple(IPv4Network(cidr) for cidr in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def is_local(address):
    return any(address in network for network in LOCAL_NETWORKS)


def default_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('1.1.1.1', 443))  # Inspect the route without contacting the Internet.
            address = IPv4Address(route.getsockname()[0])
            if is_local(address):
                return address
    except OSError:
        pass

    # A Wi-Fi or hotspot can still host the app after its default route disappears.
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         "Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred | "
         "Where-Object { $_.InterfaceAlias -notlike 'vEthernet*' } | Select-Object -ExpandProperty IPAddress"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    candidates = {IPv4Address(line.strip()) for line in result.stdout.splitlines() if line.strip()}
    candidates = sorted(address for address in candidates if is_local(address))
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise ValueError('Hay varias IPv4 locales. Usa --bind con la de tu red: ' + ', '.join(map(str, candidates)))
    raise ValueError('Conecta el PC al Wi-Fi o hotspot y vuelve a abrir el iniciador. Puedes indicar la IPv4 con --bind.')


def lan_is_running(url, ca_file):
    if not ca_file.is_file():
        return False
    try:
        context = ssl.create_default_context(cadata=ca_file.read_bytes())
        client = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
        with client.open(url + '/api/v1/health', timeout=2) as response:
            health = json.load(response)
            return health == {'status': 'ok', 'environment': 'development', 'database': 'postgresql-postgis'}
    except (ValueError, OSError):
        return False


def show_lan_url(url, ca_file):
    public_ca = ROOT / '.runtime' / 'GeoCattle-LAN-CA.cer'
    public_ca.parent.mkdir(parents=True, exist_ok=True)
    public_ca.write_bytes(ca_file.read_bytes())
    (public_ca.parent / 'GeoCattle-LAN-URL.txt').write_text(url + '/\n', encoding='utf-8')
    print(f'GeoCattle en la red local: {url}/', flush=True)
    print(f'Certificado público para los clientes: {public_ca}', flush=True)


def name(label):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])


def certificate(subject, issuer, key, now, duration):
    return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + duration))


def write_key(path, key):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                     serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def tls_files(directory, address):
    directory.mkdir(parents=True, exist_ok=True)
    ca_file = directory / 'GeoCattle-LAN-CA.cer'
    ca_key_file = directory / 'ca-key.pem'
    now = datetime.now(timezone.utc)
    if ca_file.exists() != ca_key_file.exists():
        raise ValueError('Falta un archivo de la autoridad LAN. Recupera el par antes de iniciar.')
    if ca_file.exists():
        ca = x509.load_der_x509_certificate(ca_file.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), password=None)
        ca.verify_directly_issued_by(ca)
        if ca.public_key().public_numbers() != ca_key.public_key().public_numbers():
            raise ValueError('El certificado y la clave de la autoridad LAN no coinciden.')
        if ca.not_valid_after_utc <= now:
            raise ValueError('La autoridad LAN venció. Conserva una copia del par antes de renovarlo.')
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = name('GeoCattle LAN')
        ca = (certificate(ca_name, ca_name, ca_key, now, timedelta(days=730))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                             data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                             encipher_only=False, decipher_only=False), critical=True)
              .sign(ca_key, hashes.SHA256()))
        write_key(ca_key_file, ca_key)
        ca_file.write_bytes(ca.public_bytes(serialization.Encoding.DER))

    key_file = directory / 'server-key.pem'
    cert_file = directory / 'server.pem'
    server_key = ec.generate_private_key(ec.SECP256R1())
    lifetime = min(timedelta(days=90), ca.not_valid_after_utc - now)
    server = (certificate(name(str(address)), ca.subject, server_key, now, lifetime)
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.public_key()), critical=False)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
              .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]), critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
              .sign(ca_key, hashes.SHA256()))
    write_key(key_file, server_key)
    cert_file.write_bytes(server.public_bytes(serialization.Encoding.PEM))
    return ca_file, cert_file, key_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', type=IPv4Address, help='IPv4 privada de la interfaz conectada a la red local')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Este iniciador usa el prototipo nativo de Windows.')
    try:
        address = args.bind or default_address()
    except ValueError as error:
        parser.error(str(error))
    except (OSError, subprocess.SubprocessError):
        parser.error('No se pudo detectar la red local. Indica su IPv4 con --bind.')
    if not is_local(address):
        parser.error('Elige una IPv4 privada del equipo con --bind.')

    url = f'https://{address}:{PORT}'
    tls_directory = Path(os.environ['LOCALAPPDATA']) / 'GeoCattle' / 'lan-tls'
    ca_file = tls_directory / 'GeoCattle-LAN-CA.cer'
    if lan_is_running(url, ca_file):
        show_lan_url(url, ca_file)
        print('El servidor HTTPS ya está iniciado.', flush=True)
        return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((str(address), PORT))
        except OSError as error:
            parser.error(f'No se puede abrir {address}:{PORT}. Comprueba la IP y el puerto: {error}')

    env = environment()
    if env.get('APP_ENV') != 'development' or not listening(int(env['DB_PORT'])):
        parser.error('Inicia primero el prototipo de desarrollo con Abrir-GeoCattle.cmd.')
    if not (ROOT / 'frontend' / 'dist' / 'index.html').is_file():
        parser.error('Falta compilar la interfaz. Ejecuta npm run build desde frontend.')
    try:
        ca_file, cert_file, key_file = tls_files(tls_directory, address)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    os.environ.update(env, ALLOWED_ORIGINS=url, COOKIE_SECURE='true',
                      ADMIN_LOGIN_MFA='true', LOCAL_ADMIN_PASSWORD_ONLY='false')
    sys.path.insert(0, str(ROOT / 'backend'))
    import uvicorn

    class LanServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                show_lan_url(url, ca_file)

    config = uvicorn.Config('geocattle.local_app:app', host=str(address), port=PORT, proxy_headers=False,
                            ssl_certfile=str(cert_file), ssl_keyfile=str(key_file))
    server = LanServer(config)
    server.run()
    if not server.started:
        sys.exit(1)


if __name__ == '__main__':
    main()
