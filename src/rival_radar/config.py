from pydantic import model_validator
from pydantic_settings import BaseSettings

_INSECURE_SECRET_KEY = "dev-secret-key-change-in-production"
_INSECURE_PASSWORD = "changeme"


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    slack_webhook_url: str = ""
    database_url: str = "sqlite:///./rival_radar.db"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    dashboard_password: str = _INSECURE_PASSWORD
    google_client_id: str = ""
    google_client_secret: str = ""
    secret_key: str = _INSECURE_SECRET_KEY

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _require_secure_secrets_in_production(self) -> "Settings":
        if "postgresql" not in self.database_url:
            return self  # dev / test — skip
        errors: list[str] = []
        if self.secret_key == _INSECURE_SECRET_KEY:
            errors.append("SECRET_KEY must be changed from the default in production")
        if self.dashboard_password == _INSECURE_PASSWORD:
            errors.append("DASHBOARD_PASSWORD must be changed from the default in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self


settings = Settings()
