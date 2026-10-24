"""Run versioned SQL migrations transactionally. No ORM create_all in production."""
from pathlib import Path
from sqlalchemy import text
from .db import engine
from .settings import settings
from psycopg import sql

def migrate():
    migrations = Path(__file__).resolve().parents[2] / "database" / "migrations"
    if not migrations.exists(): migrations = Path("/database/migrations")
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(804193811)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"))
        for path in sorted(migrations.glob("*.sql")):
            if conn.execute(text("SELECT 1 FROM schema_migrations WHERE version=:v"), {"v":path.name}).scalar(): continue
            conn.connection.driver_connection.execute(path.read_text(encoding='utf-8'), prepare=False)
            conn.execute(text("INSERT INTO schema_migrations(version) VALUES(:v)"), {"v":path.name})
            print(f"Applied {path.name}")
        if settings().app_database_password:
            raw=conn.connection.driver_connection
            if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='geocattle_app'")).scalar():
                raw.execute("CREATE ROLE geocattle_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
            raw.execute(sql.SQL("ALTER ROLE geocattle_app PASSWORD {}").format(sql.Literal(settings().app_database_password)))
            raw.execute("GRANT USAGE ON SCHEMA public TO geocattle_app")
            raw.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO geocattle_app")
            raw.execute("REVOKE UPDATE,DELETE ON telemetry,telemetry_receptions,event_actions,audit_log,notification_attempts,maintenance,change_requests,change_decisions,change_applications,animal_measurements,animal_reports,health_events,health_treatments,health_schedules,request_metrics,movement_status_events FROM geocattle_app")
            raw.execute("REVOKE INSERT,UPDATE,DELETE ON schema_migrations FROM geocattle_app")
            raw.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
if __name__ == "__main__": migrate()
