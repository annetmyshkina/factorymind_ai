from pydantic import Field, model_validator
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

    @model_validator(mode="after")
    def lease_covers_llm_timeout(self) -> "Settings":
        if self.experiment_worker_lease_seconds <= self.llm_timeout_seconds:
            raise ValueError(
                "EXPERIMENT_WORKER_LEASE_SECONDS должен быть больше "
                "LLM_TIMEOUT_SECONDS",
            )
        return self


settings = Settings()
