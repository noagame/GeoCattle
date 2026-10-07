from functools import lru_cache
from typing import Literal
from pydantic import model_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = Field(default="postgresql+psycopg://geocattle:geocattle@localhost:5432/geocattle_sim", repr=False)
    app_database_password: str | None = Field(default=None, repr=False)
    app_env: Literal["simulation", "development", "production"] = "development"
    simulation_enabled: bool = False
    session_secret: str = Field(default="development-change-this-secret-before-use", repr=False)
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
    notification_webhook_url: str | None = None
    notification_webhook_token: str | None = Field(default=None, repr=False)
    notification_max_attempts: int = 3
    notification_expiry_hours: int = 24
    worker_interval_seconds: int = 15
    config_timeout_seconds: int = 3600
    config_downlink_enabled: bool = False
    config_codec_validated: bool = False
    chirpstack_application_id: str | None = None
    config_fport: int = 10

    @model_validator(mode="after")
    def isolation(self):
        if self.simulation_enabled and self.app_env != "simulation":
            raise ValueError("SIMULATION_ENABLED requiere APP_ENV=simulation")
        if self.app_env == "production":
            if not self.cookie_secure or len(self.session_secret) < 32 or self.session_secret.startswith("development") or len(self.ingest_key) < 32 or self.ingest_key.startswith("development"):
                raise ValueError("Producción requiere COOKIE_SECURE y secretos únicos de al menos 32 caracteres")
            if self.demo_password:
                raise ValueError("DEMO_PASSWORD no se permite en producción")
        if self.config_downlink_enabled:
            import re
            if self.app_env=="simulation" or not self.config_codec_validated or not self.chirpstack_application_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",self.chirpstack_application_id) or not 1<=self.config_fport<=223:
                raise ValueError("Downlink requiere ambiente real, CONFIG_CODEC_VALIDATED, APPLICATION_ID válido y FPort 1..223")
        if not self.database_url.startswith("postgresql"):
            raise ValueError("La base de aplicación debe ser PostgreSQL/PostGIS")
        return self

@lru_cache
def settings() -> Settings:
    return Settings()
