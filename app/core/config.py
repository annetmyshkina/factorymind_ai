from pydantic import Field, SecretStr, model_validator
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

    auth_jwt_secret: SecretStr = SecretStr(
        "development-only-factorymind-secret-change-before-production",
    )
    auth_jwt_issuer: str = "factorymind-ai"
    auth_jwt_audience: str = "factorymind-api"
    auth_access_token_minutes: int = Field(default=30, gt=0, le=1440)
    auth_bootstrap_enabled: bool = True
    auth_bootstrap_username: str = "admin"
    auth_bootstrap_password: SecretStr = SecretStr("admin")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_telemetry_topic: str = "factorymind/equipment/+/telemetry"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"

    compatible_base_url: str | None = None
    compatible_model: str | None = None
    compatible_api_key: str | None = None
    compatible_auth_scheme: str = "Bearer"

    llm_timeout_seconds: float = 60.0
    experiment_worker_lease_seconds: int = Field(default=120, gt=0)
    experiment_worker_poll_seconds: float = Field(default=1.0, gt=0)
    experiment_max_attempts: int = Field(default=3, gt=0)
    experiment_retry_base_seconds: int = Field(default=5, gt=0)
    experiment_worker_metrics_host: str = "127.0.0.1"
    experiment_worker_metrics_port: int = Field(default=9101, ge=1, le=65535)

    telegram_notifications_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_timeout_seconds: float = Field(default=10.0, gt=0)
    public_app_base_url: str | None = None
    notification_worker_lease_seconds: int = Field(default=30, gt=0)
    notification_worker_poll_seconds: float = Field(default=1.0, gt=0)
    notification_max_attempts: int = Field(default=3, gt=0)
    notification_retry_base_seconds: int = Field(default=5, gt=0)
    notification_worker_metrics_host: str = "127.0.0.1"
    notification_worker_metrics_port: int = Field(default=9102, ge=1, le=65535)

    @model_validator(mode="after")
    def lease_covers_llm_timeout(self) -> "Settings":
        if len(self.auth_jwt_secret.get_secret_value()) < 32:
            raise ValueError("AUTH_JWT_SECRET должен содержать не менее 32 символов")
        if self.environment not in {"development", "test"}:
            if self.auth_jwt_secret.get_secret_value().startswith(
                "development-only-",
            ):
                raise ValueError(
                    "AUTH_JWT_SECRET должен быть заменён вне development/test",
                )
            if self.auth_bootstrap_enabled:
                raise ValueError(
                    "AUTH_BOOTSTRAP_ENABLED должен быть false вне development/test",
                )
        if self.experiment_worker_lease_seconds <= self.llm_timeout_seconds:
            raise ValueError(
                "EXPERIMENT_WORKER_LEASE_SECONDS должен быть больше "
                "LLM_TIMEOUT_SECONDS",
            )
        token_value = (
            self.telegram_bot_token.get_secret_value().strip()
            if self.telegram_bot_token is not None
            else ""
        )
        chat_id = self.telegram_chat_id.strip() if self.telegram_chat_id else ""
        if self.telegram_notifications_enabled and (not token_value or not chat_id):
            raise ValueError(
                "Для Telegram-уведомлений нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID",
            )
        if self.notification_worker_lease_seconds <= self.telegram_timeout_seconds:
            raise ValueError(
                "NOTIFICATION_WORKER_LEASE_SECONDS должен быть больше "
                "TELEGRAM_TIMEOUT_SECONDS",
            )
        return self


settings = Settings()
