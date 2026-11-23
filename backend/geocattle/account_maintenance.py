"""Mantenimiento local de cuentas. Este módulo no tiene punto de entrada HTTP."""
import argparse
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


def reset_totp(db, email, environment):
    from .models import User
    from .v3_security import execute, retire_mfa_access, rows

    identities = rows(db, """SELECT u.id FROM users u WHERE u.active
        AND coalesce(u.email,lower(u.username))=:email
        AND (u.farm_id IS NULL OR EXISTS (
            SELECT 1 FROM farms f WHERE f.id=u.farm_id AND f.environment=:env))
        ORDER BY u.id LIMIT 2 FOR UPDATE""", email=email.strip().lower(), env=environment)
    if len(identities) != 1:
        return
    user_id = identities[0]['id']
    db.get(User, user_id).mfa_enrollment_required = True
    retire_mfa_access(db, user_id)
    execute(db, """INSERT INTO audit_log(id,actor_kind,object_type,object_id,action,at,after)
        VALUES(:i,'service','security',:u,'mfa_reset_console',now(),
            jsonb_build_object('actor','sistema/consola','all_sessions_revoked',true,'enrollment_required',true))""",
        i=uuid4(), u=str(user_id))


def main():
    from .settings import settings

    parser = argparse.ArgumentParser(description='Mantenimiento local de cuentas GeoCattle')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('smtp-test', help='Envía un correo de prueba').add_argument('--to', required=True)
    commands.add_parser('mfa-reset', help='Restablece el TOTP de una cuenta').add_argument('--email', required=True)
    args = parser.parse_args()
    try:
        cfg = settings()
    except ValidationError as error:
        # Settings omit input values. Emitting only validation messages also
        # keeps secrets out of CLI output when a private file is malformed.
        for issue in error.errors(include_input=False, include_context=False, include_url=False):
            print(f"Configuración inválida. {issue['msg']}")
        return 1
    if args.command == 'smtp-test':
        from .invitation_mail import send_test_mail, smtp_error_message

        try:
            send_test_mail(cfg, args.to.strip())
        except ValueError as error:
            print(str(error))
            return 1
        except OSError as error:
            print(smtp_error_message(error))
            return 1
        print('El servidor SMTP aceptó el correo de prueba.')
    else:
        from .db import SessionLocal

        email = args.email.strip()
        if '@' not in email or len(email) > 254 or any(character.isspace() for character in email):
            parser.error('Indica un correo de acceso válido')
        try:
            with SessionLocal.begin() as db:
                reset_totp(db, email, cfg.app_env)
        except (SQLAlchemyError, ValueError):
            print('No se pudo ejecutar el restablecimiento. Revisa la conexión y las migraciones de GeoCattle.')
            return 1
        print('Solicitud procesada. Si correspondía a una cuenta activa, deberá inscribir un autenticador al ingresar.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
