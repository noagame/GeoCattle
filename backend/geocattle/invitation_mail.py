"""Send invitation and acceptance messages over authenticated TLS SMTP."""
import logging
import smtplib
import ssl
from email.errors import MessageError
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate

from cryptography.fernet import InvalidToken

from .settings import settings
from .v3_security import cipher, execute, one


log = logging.getLogger(__name__)
ROLE_LABELS = {'worker': 'trabajador', 'veterinarian': 'veterinario'}
MAX_ATTEMPTS = 3


def invitation_url(token, cfg):
    return f"{cfg.invitation_base_url.rstrip('/')}/#enrol={token}"


def queue_invitation(db, invitation_id, recipient, token):
    execute(db, """INSERT INTO invitation_mail(invitation_id,kind,recipient,encrypted_token)
        VALUES(:i,'invitation',:r,:t)""",
        i=invitation_id, r=recipient, t=cipher().encrypt(token.encode('ascii')))


def queue_acceptance(db, invitation):
    inviter = one(db, "SELECT coalesce(email,username) AS email FROM users WHERE id=:u AND active",
                  u=invitation['invited_by'])
    if inviter:
        execute(db, """INSERT INTO invitation_mail(invitation_id,kind,recipient)
            VALUES(:i,'accepted',:r) ON CONFLICT DO NOTHING""",
            i=invitation['id'], r=inviter['email'])


def new_message(cfg, recipient):
    _, _, _, _, sender = cfg.mail_connection()
    message = EmailMessage()
    message['From'] = Address('GeoCattle', username=sender.username, domain=sender.domain)
    message['To'] = Address(addr_spec=recipient)
    message['Date'] = formatdate()
    return message


def send_message(cfg, message):
    host, port, username, password, _ = cfg.mail_connection()
    context = ssl.create_default_context()
    timeout = cfg.smtp_timeout_seconds
    if cfg.smtp_tls_mode == 'ssl':
        smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)
    try:
        if cfg.smtp_tls_mode == 'starttls':
            smtp.starttls(context=context)
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    finally:
        smtp.close()


def smtp_code(error):
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return next((code for code, _ in error.recipients.values()), None)
    if isinstance(error, smtplib.SMTPResponseException):
        return error.smtp_code
    return None


def smtp_error_message(error):
    code = smtp_code(error)
    suffix = f' (SMTP {code})' if code else ''
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return 'El servidor rechazó la autenticación. Revisa la cuenta y la contraseña SMTP' + suffix
    if isinstance(error, ssl.SSLError):
        return 'Falló la conexión TLS. Revisa el modo TLS, el puerto y el certificado del servidor'
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return 'El servidor no anuncia STARTTLS, autenticación u otra capacidad SMTP requerida'
    if isinstance(error, smtplib.SMTPSenderRefused):
        return 'El servidor rechazó la dirección del remitente' + suffix
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return 'El servidor rechazó la dirección del destinatario' + suffix
    if isinstance(error, TimeoutError):
        return 'Se agotó el tiempo de espera SMTP. Revisa la conectividad y el puerto'
    if code:
        return 'El servidor rechazó el envío' + suffix
    return 'No se pudo establecer o mantener la conexión SMTP. Revisa el servidor y el puerto'


def send_test_mail(cfg, recipient):
    try:
        address = Address(addr_spec=recipient)
        if not address.username or not address.domain or '\n' in recipient or '\r' in recipient:
            raise ValueError
    except (MessageError, ValueError):
        raise ValueError('Indica una dirección de correo válida') from None
    message = new_message(cfg, address.addr_spec)
    message['Subject'] = 'Prueba de correo de GeoCattle'
    message.set_content('GeoCattle se conectó al servidor SMTP y pudo enviar este mensaje de prueba.')
    send_message(cfg, message)


def process_invitation_mail(db):
    execute(db, """UPDATE invitation_mail m SET status=CASE
          WHEN m.kind='invitation' AND (i.accepted_at IS NOT NULL OR i.revoked_at IS NOT NULL)
            THEN 'cancelled' ELSE 'expired' END, encrypted_token=NULL
        FROM invitations i WHERE i.id=m.invitation_id AND m.status='pending' AND (
          (m.kind='invitation' AND (i.expires_at<=now() OR i.accepted_at IS NOT NULL OR i.revoked_at IS NOT NULL))
          OR (m.kind='accepted' AND m.created_at<=now()-interval '48 hours'))""")
    cfg = settings()
    if not cfg.invitation_email_enabled:
        return
    item = one(db, """SELECT m.invitation_id,m.kind,m.recipient,m.encrypted_token,m.attempts,
          i.role_code,i.email,f.name AS farm_name,u.full_name AS accepted_name
        FROM invitation_mail m JOIN invitations i ON i.id=m.invitation_id
        JOIN farms f ON f.id=i.farm_id JOIN owner_accounts a ON a.id=f.account_id
        LEFT JOIN users u ON u.id=i.accepted_user_id
        WHERE m.status='pending' AND m.next_attempt_at<=now() AND f.active AND a.active
          AND (m.kind='accepted' OR (i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>now()))
          AND f.environment=:env ORDER BY m.next_attempt_at,m.invitation_id LIMIT 1
        FOR UPDATE OF i,m SKIP LOCKED""", env=cfg.app_env)
    if not item:
        return

    farm = item['farm_name']
    status = 'sent'
    try:
        role = ROLE_LABELS[item['role_code']]
        message = new_message(cfg, item['recipient'])
        domain = message['From'].addresses[0].domain
        message['Message-ID'] = f"<geocattle.{item['invitation_id']}.{item['kind']}@{domain}>"
        if item['kind'] == 'invitation':
            token = cipher().decrypt(bytes(item['encrypted_token'])).decode('ascii')
            message['Subject'] = 'Invitación a GeoCattle'
            message.set_content(f"Te invitaron a {farm} como {role}.\n\nAcepta tu invitación en GeoCattle:\n"
                                f"{invitation_url(token, cfg)}\n\nEl enlace vence 48 horas después de su creación.")
        else:
            name = item['accepted_name'] or item['email']
            message['Subject'] = 'Invitación aceptada en GeoCattle'
            message.set_content(f"{name} aceptó la invitación para {farm} con el perfil {role}.\n")
        send_message(cfg, message)
    except (InvalidToken, MessageError, ValueError, KeyError) as error:
        log.warning("Correo de invitación %s inválido: %s", item['invitation_id'], type(error).__name__)
        status = 'failed'
    except OSError as error:
        code = smtp_code(error)
        log.warning("Fallo SMTP de invitación %s: %s, código %s",
                    item['invitation_id'], type(error).__name__, code)
        permanent = code is not None and 500 <= code < 600
        status = 'pending' if not permanent and item['attempts'] + 1 < MAX_ATTEMPTS else 'failed'
    execute(db, """UPDATE invitation_mail
        SET attempts=attempts+1, status=:s, next_attempt_at=now()+make_interval(secs=>:delay),
            sent_at=CASE WHEN :s='sent' THEN now() END,
            encrypted_token=CASE WHEN :s='pending' THEN encrypted_token END
        WHERE invitation_id=:i AND kind=:k""",
        s=status, delay=60 * 2 ** item['attempts'], i=item['invitation_id'], k=item['kind'])
