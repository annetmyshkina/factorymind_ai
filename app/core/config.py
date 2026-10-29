from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FactoryMind AI"
    app_version: str = "0.1.0"
    environment: str = "development"

    postgres_user: str = "factorymind"
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "factorymind"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_telemetry_topic: str = "factorymind/equipment/+/telemetry"


settings = Settings()
