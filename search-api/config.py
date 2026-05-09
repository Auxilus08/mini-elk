from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    es_host: str = "http://elasticsearch:9200"
    es_index_logs: str = "logs-*"
    es_index_anomalies: str = "anomalies-*"
    es_timeout: int = 10
    max_result_size: int = 1000
    default_result_size: int = 100
    anomaly_window_minutes: int = 5
    cors_origins: List[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_prefix="SEARCH_API_", case_sensitive=False)


def get_settings() -> Settings:
    return Settings()
