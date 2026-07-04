from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # AI — Gemini (Google AI Studio)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"

    # Database
    database_url: str = "sqlite:///./dealyze.db"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 h

    # Paddle (paiements réels — international + Afrique)
    paddle_api_key: str = ""
    paddle_webhook_secret: str = ""
    paddle_price_starter: str = ""      # pri_... — 47 USD/mois
    paddle_price_growth: str = ""       # pri_... — 147 USD/mois
    paddle_price_enterprise: str = ""   # pri_... — 477 USD/mois

    # Mode simulation (true = pas besoin de compte Paddle)
    simulation_mode: bool = False

    # URL de redirection après paiement
    app_url: str = "http://localhost:3000"

    # App
    app_env: str = "development"
    app_version: str = "0.1.0"


settings = Settings()
