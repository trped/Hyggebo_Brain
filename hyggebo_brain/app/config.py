"""Configuration from environment variables (set by bashio in run.sh)."""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Application settings from environment."""

    # MQTT (EMQX)
    mqtt_host: str = os.environ.get("MQTT_HOST", "a0d7b954-emqx")
    mqtt_port: int = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_user: str = os.environ.get("MQTT_USER", "admin")
    mqtt_password: str = os.environ.get("MQTT_PASSWORD", "")

    # PostgreSQL
    pg_host: str = os.environ.get("PG_HOST", "db21ed7f-postgres-latest")
    pg_port: int = int(os.environ.get("PG_PORT", "5432"))
    pg_database: str = os.environ.get("PG_DATABASE", "hyggebo_brain")
    pg_user: str = os.environ.get("PG_USER", "brain_user")
    pg_password: str = os.environ.get("PG_PASSWORD", "brain_secure_2026")

    # General
    log_level: str = os.environ.get("LOG_LEVEL", "info")
    supervisor_token: str = os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def pg_dsn(self) -> str:
        """PostgreSQL connection string for asyncpg."""
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )
