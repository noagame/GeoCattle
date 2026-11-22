"""Exercise SMTP against an isolated server with both supported TLS modes."""
import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import os
import socketserver
import ssl
import subprocess
import sys
import threading
from uuid import UUID, uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
from sqlalchemy import text

from geocattle.invitation_mail import process_invitation_mail
from geocattle.settings import settings
from test_v3_api import PASSWORD, enable_owner_mfa, operation_write, v3


SMTP_USER = 'sender@example.test'
SMTP_PASSWORD = 'qa-only-smtp-secret'


class SmtpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        tls = self.server.tls_mode == 'ssl'
        sock = self.server.tls.wrap_socket(self.request, server_side=True) if tls else self.request
        sock.settimeout(3)
        stream = sock.makefile('rb')
        authenticated = False
        try:
            sock.sendall(b'220 localhost test SMTP\r\n')
            while line := stream.readline():
                command, *arguments = line.strip().split(maxsplit=1)
                command = command.upper()
                if command == b'EHLO':
                    capability = b'AUTH PLAIN' if tls else b'STARTTLS'
                    reply = b'250-localhost\r\n250 ' + capability
                elif command == b'STARTTLS' and not tls:
                    sock.sendall(b'220 Begin TLS\r\n')
                    stream.close()
                    sock = self.server.tls.wrap_socket(sock, server_side=True)
                    stream = sock.makefile('rb')
                    tls = True
                    continue
                elif command == b'AUTH' and tls:
                    plain = arguments[0].removeprefix(b'PLAIN ')
                    expected = b'\0' + SMTP_USER.encode() + b'\0' + SMTP_PASSWORD.encode()
                    authenticated = base64.b64decode(plain) == expected
                    reply = b'235 Accepted' if authenticated else b'535 rejected ' + SMTP_PASSWORD.encode()
                elif command in (b'MAIL', b'RCPT') and authenticated:
                    reply = b'250 OK'
                elif command == b'DATA' and authenticated:
                    sock.sendall(b'354 Send message\r\n')
                    lines = []
                    while (data := stream.readline()) not in (b'', b'.\r\n'):
                        lines.append(data[1:] if data.startswith(b'..') else data)
                    code = self.server.data_replies.pop(0) if self.server.data_replies else 250
                    if code == 250:
                        self.server.messages.append(BytesParser(policy=policy.default).parsebytes(b''.join(lines)))
                    reply = f'{code} Test response {SMTP_PASSWORD}'.encode()
                else:
                    reply = b'503 Bad sequence'
                sock.sendall(reply + b'\r\n')
        finally:
            stream.close()
            sock.close()


@pytest.fixture
def smtp_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
        .sign(key, hashes.SHA256()))
    cert = tmp_path / 'smtp.pem'
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    pem = tmp_path / 'smtp-key.pem'
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    monkeypatch.setenv('SSL_CERT_FILE', str(cert))
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), SmtpHandler) as server:
        server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.tls.load_cert_chain(cert, pem)
        server.tls_mode = 'starttls'
        server.messages = []
        server.data_replies = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def test_smtp_test_command_sends_without_database_or_real_invitation(smtp_server):
    env = {**os.environ, 'INVITATION_EMAIL_ENABLED': 'false', 'SMTP_HOST': 'localhost',
        'SMTP_PORT': str(smtp_server.server_address[1]), 'SMTP_TLS_MODE': 'starttls',
        'SMTP_USERNAME': SMTP_USER, 'SMTP_PASSWORD': SMTP_PASSWORD, 'SMTP_FROM': SMTP_USER,
        'SMTP_TIMEOUT_SECONDS': '3', 'PYTHONUTF8': '1'}
    command = [sys.executable, '-m', 'geocattle.account_maintenance', 'smtp-test', '--to', 'tester@example.test']
    sent = subprocess.run(command, env=env, capture_output=True, encoding='utf-8', timeout=15)
    assert sent.returncode == 0, sent.stdout + sent.stderr
    assert 'aceptó el correo de prueba' in sent.stdout
    message, = smtp_server.messages
    assert message['To'] == 'tester@example.test'
    assert message['Subject'] == 'Prueba de correo de GeoCattle'
    assert '#enrol=' not in message.get_content()
    denied = subprocess.run(command, env={**env, 'SMTP_PASSWORD': 'invalid'}, capture_output=True, encoding='utf-8', timeout=15)
    assert denied.returncode == 1, denied.stdout + denied.stderr
    assert 'rechazó la autenticación' in denied.stdout and '(SMTP 535)' in denied.stdout
    assert SMTP_PASSWORD not in denied.stdout + denied.stderr


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS V3 de prueba')
def test_invitation_and_acceptance_over_ssl_with_retry(v3, smtp_server, monkeypatch, caplog):
    smtp_server.tls_mode = 'ssl'
    smtp_server.data_replies = [451, 250, 250]
    config = settings()
    for key, value in {
        'invitation_email_enabled': True, 'invitation_base_url': 'https://192.168.1.25:8445',
        'smtp_host': 'localhost', 'smtp_port': smtp_server.server_address[1], 'smtp_tls_mode': 'ssl',
        'smtp_username': SMTP_USER, 'smtp_password': SMTP_PASSWORD, 'smtp_from': SMTP_USER,
        'smtp_timeout_seconds': 3,
    }.items():
        monkeypatch.setattr(config, key, value)
    owner = v3.client('owner')
    secret = enable_owner_mfa(v3, owner)
    path = '/api/v1/v3/invitations'
    response = operation_write(v3, owner, secret, 'POST', path,
        {'role_code': 'worker', 'email': f'collaborator-{uuid4().hex}@example.test'})
    assert response.status_code == 201, response.text
    invite = response.json()
    assert invite['delivery'] == 'queued' and not smtp_server.messages
    mail = {'i': UUID(invite['id'])}
    invitation_status = text("SELECT status,attempts,encrypted_token FROM invitation_mail WHERE invitation_id=:i AND kind='invitation'")
    process_invitation_mail(v3.db)
    assert v3.db.execute(invitation_status, mail).one()[:2] == ('pending', 1)
    assert SMTP_PASSWORD not in caplog.text and invite['invitation_token'] not in caplog.text
    v3.db.execute(text('UPDATE invitation_mail SET next_attempt_at=now() WHERE invitation_id=:i'), mail)
    process_invitation_mail(v3.db)
    assert v3.db.execute(invitation_status, mail).one() == ('sent', 2, None)
    assert invite['invitation_url'].startswith('https://192.168.1.25:8445/#enrol=')
    assert invite['invitation_url'] in smtp_server.messages[0].get_content()
    visitor = v3.client('worker', login=False)
    accepted = visitor.post('/api/v1/v3/enrol', json={
        'token': invite['invitation_token'], 'password': PASSWORD, 'full_name': 'Colaborador de prueba'})
    assert accepted.status_code == 201, accepted.text
    process_invitation_mail(v3.db)
    _, confirmation = smtp_server.messages
    assert confirmation['To'] == v3.users['owner'].email
    assert '#enrol=' not in confirmation.get_content()
