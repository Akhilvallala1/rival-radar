from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    slack_webhook_url: str = ""
    database_url: str = "sqlite:///./rival_radar.db"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
