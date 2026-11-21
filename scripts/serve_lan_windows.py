"""Serve the existing Windows prototype over HTTPS on a local IPv4 address."""
import argparse
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Network
import os
from pathlib import Path
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from prototype_windows import ROOT, environment, listening


PORT = 8445
LOCAL_NETWORKS = tuple(IPv4Network(cidr) for cidr in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def default_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(('1.1.1.1', 443))  # Select the outgoing interface without sending data.
        return IPv4Address(route.getsockname()[0])


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
    except OSError:
        parser.error('Indica con --bind la IPv4 del adaptador conectado a la red local.')
    if not any(address in network for network in LOCAL_NETWORKS):
        parser.error('Elige una IPv4 privada del equipo con --bind.')
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
    url = f'https://{address}:{PORT}'
    tls_directory = Path(os.environ['LOCALAPPDATA']) / 'GeoCattle' / 'lan-tls'
    try:
        ca_file, cert_file, key_file = tls_files(tls_directory, address)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    os.environ.update(env, ALLOWED_ORIGINS=url, COOKIE_SECURE='true',
                      ADMIN_LOGIN_MFA='true', LOCAL_ADMIN_PASSWORD_ONLY='false')
    sys.path.insert(0, str(ROOT / 'backend'))
    import uvicorn

    print(f'GeoCattle en la red local: {url}/', flush=True)
    public_ca = ROOT / '.runtime' / 'GeoCattle-LAN-CA.cer'
    public_ca.parent.mkdir(parents=True, exist_ok=True)
    public_ca.write_bytes(ca_file.read_bytes())
    print(f'Certificado público para los clientes: {public_ca}', flush=True)
    uvicorn.run('geocattle.local_app:app', host=str(address), port=PORT, proxy_headers=False,
                ssl_certfile=str(cert_file), ssl_keyfile=str(key_file))


if __name__ == '__main__':
    main()
