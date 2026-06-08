from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    slack_webhook_url: str = ""
    database_url: str = "sqlite:///./rival_radar.db"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    dashboard_password: str = "changeme"
    google_client_id: str = ""
    google_client_secret: str = ""
    secret_key: str = "dev-secret-key-change-in-production"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
