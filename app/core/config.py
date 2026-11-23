from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "NØRI"
    database_url: str = "sqlite:///./nori.db"
    bot_token: str = ""
    api_base_url: str = "http://127.0.0.1:8000"
    # Deprecated and ignored: v0.6 never accepts a global service bearer.
    service_token: str = ""
    owner_telegram_ids: str = ""  # bootstrap owners; protect deployment configuration
    admin_telegram_ids: str = ""  # legacy-only config, ignored by v0.6 authorization
    pairing_ttl_seconds: int = 300
    device_pairing_enabled: bool = False  # enable only in isolated test environment
    device_limit: int = 2
    v2_approved_event_types: str = ""  # explicit, externally approved types only
    v2_approved_command_types: str = ""  # no game SDK types approved by default
    auto_create_schema: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
