from functools import lru_cache
from email.errors import MessageError
from email.headerregistry import Address
from ipaddress import ip_address
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import model_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = Field(default="postgresql+psycopg://geocattle:geocattle@localhost:5432/geocattle_sim", repr=False)
    app_database_password: str | None = Field(default=None, repr=False)
    app_env: Literal["simulation", "development", "production"] = "development"
    simulation_enabled: bool = False
    session_secret: str = Field(default="development-change-this-secret-before-use", repr=False)
    mfa_encryption_key: str | None = Field(default=None, repr=False)
    admin_login_mfa: bool = False
    local_admin_password_only: bool = False
    ingest_key: str = Field(default="development-change-this-ingest-key", repr=False)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"
    session_hours: int = 12
    demo_password: str | None = Field(default=None, repr=False)
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = Field(default=None, repr=False)
    mqtt_topic: str = "geocattle/academic/telemetry"
    mqtt_ack_topic: str = "geocattle/academic/committed"
    mqtt_client_id: str = "geocattle-ingestor"
    mqtt_tls: bool = False
    mqtt_spool_path: str = "/data/mqtt-spool.sqlite3"
    preventive_rules_validated: bool = False
    prototype_temperature_enabled: bool = False
    notification_webhook_url: str | None = None
    notification_webhook_token: str | None = Field(default=None, repr=False)
    notification_max_attempts: int = 3
    notification_expiry_hours: int = 24
    invitation_email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_tls_mode: Literal["ssl", "starttls"] = "ssl"
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = ""
    smtp_timeout_seconds: float = Field(default=8, gt=0, le=60)
    gmail_smtp_from: str | None = None
    gmail_smtp_app_password: str | None = Field(default=None, repr=False)
    invitation_base_url: str | None = None
    worker_interval_seconds: int = 15
    config_timeout_seconds: int = 3600
    config_downlink_enabled: bool = False
    config_codec_validated: bool = False
    chirpstack_application_id: str | None = None
    config_fport: int = 10

    @property
    def admin_login_requires_mfa(self) -> bool:
        return self.app_env == "production" or self.admin_login_mfa

    def mail_connection(self):
        if self.smtp_host.strip():
            host = self.smtp_host.strip()
            username = self.smtp_username.strip()
            password = self.smtp_password
            sender = self.smtp_from.strip()
        elif self.gmail_smtp_from and self.gmail_smtp_app_password:
            host = 'smtp.gmail.com'
            username = sender = self.gmail_smtp_from
            password = self.gmail_smtp_app_password
        else:
            raise ValueError("Configura SMTP_HOST o GMAIL_SMTP_FROM y GMAIL_SMTP_APP_PASSWORD")
        if bool(username) != bool(password):
            raise ValueError("SMTP_USERNAME y SMTP_PASSWORD deben configurarse juntos")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError("SMTP_HOST debe contener solo el nombre del servidor o una IPv4")
        try:
            address = Address(addr_spec=sender)
            if not address.username or not address.domain:
                raise ValueError
        except (ValueError, MessageError):
            raise ValueError("SMTP_FROM debe ser una dirección de correo válida") from None
        port = self.smtp_port or (465 if self.smtp_tls_mode == 'ssl' else 587)
        return host, port, username, password, address

    @model_validator(mode="before")
    @classmethod
    def optional_smtp_port(cls, values):
        if values.get("smtp_port") == "":
            values["smtp_port"] = None
        return values

    @model_validator(mode="after")
    def isolation(self):
        if self.local_admin_password_only and self.app_env != "development":
            raise ValueError("LOCAL_ADMIN_PASSWORD_ONLY requiere APP_ENV=development")
        if self.simulation_enabled and self.app_env != "simulation":
            raise ValueError("SIMULATION_ENABLED requiere APP_ENV=simulation")
        if self.app_env == "production":
            if not self.cookie_secure or len(self.session_secret) < 32 or self.session_secret.startswith("development") or len(self.ingest_key) < 32 or self.ingest_key.startswith("development"):
                raise ValueError("Producción requiere COOKIE_SECURE y secretos únicos de al menos 32 caracteres")
            if self.demo_password:
                raise ValueError("DEMO_PASSWORD no se permite en producción")
        if self.config_downlink_enabled:
            if self.app_env=="simulation" or not self.config_codec_validated or not self.chirpstack_application_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",self.chirpstack_application_id) or not 1<=self.config_fport<=223:
                raise ValueError("Downlink requiere ambiente real, CONFIG_CODEC_VALIDATED, APPLICATION_ID válido y FPort 1..223")
        self.gmail_smtp_from = (self.gmail_smtp_from or '').strip().lower()
        self.gmail_smtp_app_password = ''.join((self.gmail_smtp_app_password or '').split())
        if self.invitation_email_enabled:
            self.mail_connection()
            self.invitation_base_url = (self.invitation_base_url or '').strip()
            try:
                base = urlsplit(self.invitation_base_url)
            except ValueError:
                raise ValueError("INVITATION_BASE_URL no es una URL válida") from None
            host = base.hostname or ''
            try:
                loopback = ip_address(host).is_loopback
            except ValueError:
                loopback = host.rstrip('.') == 'localhost'
            local_test = self.app_env != 'production' and loopback and base.scheme == 'http'
            if (not host or '@' in base.netloc or '?' in self.invitation_base_url or '#' in self.invitation_base_url
                    or re.search(r'[\s\\]', self.invitation_base_url)
                    or (base.scheme != 'https' and not local_test)):
                raise ValueError("INVITATION_BASE_URL requiere HTTPS. HTTP local se admite en desarrollo y simulación.")
            try:
                _ = base.port
            except ValueError:
                raise ValueError("INVITATION_BASE_URL contiene un puerto inválido") from None
            if len(self.session_secret) < 32 or self.session_secret.startswith(('development', 'GENERATE')):
                raise ValueError("El correo de invitación requiere un SESSION_SECRET generado para cifrar los enlaces pendientes")
        if not self.database_url.startswith("postgresql"):
            raise ValueError("La base de aplicación debe ser PostgreSQL/PostGIS")
        return self

    @property
    def preventive_rules_allowed(self) -> bool:
        return self.app_env == "simulation" or self.preventive_rules_validated

    @property
    def temperature_rule_allowed(self) -> bool:
        return self.preventive_rules_allowed or (self.app_env == "development" and self.prototype_temperature_enabled)

@lru_cache
def settings() -> Settings:
    return Settings()
