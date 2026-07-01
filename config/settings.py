from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # AI
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Database
    database_url: str = "sqlite:///./dealyze.db"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 h

    # Lemon Squeezy (paiements réels — fonctionne depuis le Bénin)
    lemonsqueezy_api_key: str = ""
    lemonsqueezy_store_id: str = ""
    lemonsqueezy_webhook_secret: str = ""
    # Variant IDs des 3 plans (créer dans le dashboard Lemon Squeezy)
    ls_variant_starter: str = ""      # 47 USD/mois
    ls_variant_growth: str = ""       # 147 USD/mois
    ls_variant_enterprise: str = ""   # 477 USD/mois

    # Mode simulation (true = pas besoin de compte Lemon Squeezy)
    simulation_mode: bool = False

    # URL de redirection après paiement
    app_url: str = "http://localhost:3000"

    # App
    app_env: str = "development"
    app_version: str = "0.1.0"


settings = Settings()
